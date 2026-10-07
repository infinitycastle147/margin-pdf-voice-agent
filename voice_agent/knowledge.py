"""Validated knowledge models and pure normalization rules (no network access)."""

from hashlib import sha256
import unicodedata
from typing import Literal
from pydantic import BaseModel, Field


EntityKind = Literal['person', 'organization', 'place', 'product', 'process', 'concept', 'event', 'metric']


class Intent(BaseModel):
    topic: str = Field(description='Short resolved subject of inquiry, not a verbatim question')
    focus: str = Field(description='What the user wants to understand; resolve follow-up references from history')


class Entity(BaseModel):
    name: str
    kind: EntityKind
    aliases: list[str] = Field(default_factory=list)
    existing_id: str | None = Field(default=None, description='Reuse a supplied registry ID only for the exact same real-world entity')


class Citation(BaseModel):
    page_number: int
    quote: str


class Claim(BaseModel):
    subject: str = Field(description='Exact name from the entities list')
    relation: str = Field(description='Specific directed verb phrase, e.g. manufactures, requires, reduces')
    object: str = Field(description='Exact name from the entities list')
    qualifiers: str = Field(default='', description='Preserve timeframe, conditions, quantities, uncertainty and negation')
    evidence: list[Citation] = Field(default_factory=list)
    replaces_claim_id: str | None = Field(default=None, description='Existing claim ID to revise when new source evidence corrects its relation or scope')


class EntityUpdate(BaseModel):
    existing_id: str = Field(description='ID of an existing entity; never creates a node')
    detail: str = Field(description='One concise, useful fact about this entity')
    evidence: list[Citation] = Field(default_factory=list)
    replaces_detail: str | None = Field(default=None, description='Exact existing detail to correct, if new evidence contradicts it')


class ClaimRetraction(BaseModel):
    existing_id: str = Field(description='ID of a saved claim contradicted by source evidence')
    reason: str = Field(description='Concise explanation of the contradiction')
    evidence: list[Citation] = Field(default_factory=list)


class Extraction(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    entity_updates: list[EntityUpdate] = Field(default_factory=list)
    retractions: list[ClaimRetraction] = Field(default_factory=list)


class Verdict(BaseModel):
    index: int
    supported: bool
    reason: str = Field(description='Brief evidence-based validation explanation, not internal reasoning')


class Review(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)
    update_verdicts: list[Verdict] = Field(default_factory=list)
    retraction_verdicts: list[Verdict] = Field(default_factory=list)


def normalize(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def stable_id(*parts: str) -> str:
    return sha256('\x1f'.join(parts).encode()).hexdigest()[:32]


def prepare_candidates(extraction: Extraction, pages: list[dict], registry: list[dict], document_id: str,
                       existing_claims: list[dict] | None = None):
    """Fail closed on unknown endpoints, vague relations, or altered/nonexistent evidence.

    Exact name + type identity is automatic. Model-proposed alias identity requires
    a known alias in the registry, preventing silent merges of merely similar entities.
    """
    registered = {e['id']: e for e in registry}
    page_text = {p['page_number']: p['content'] for p in pages}
    entities = {}
    ambiguous = set()
    source_text = normalize(' '.join(page_text.values()))
    for entity in extraction.entities[:60]:
        name = entity.name.strip()
        if not name or len(name) > 160:
            continue
        existing = registered.get(entity.existing_id)
        if existing and existing['kind'] == entity.kind and normalize(name) in {
            normalize(existing['name']), *(normalize(a) for a in existing.get('aliases', []))
        }:
            entity_id = existing['id']
            name = existing['name']
        else:
            entity_id = stable_id(document_id, entity.kind, normalize(name))
        key = normalize(entity.name)
        if key in entities and entities[key]['id'] != entity_id:
            ambiguous.add(key)
        known_aliases = existing.get('aliases', []) if existing and existing['id'] == entity_id else []
        entities[key] = {
            'id': entity_id, 'name': name, 'kind': entity.kind,
            'aliases': sorted({a.strip() for a in [*known_aliases, *entity.aliases]
                               if a.strip() and len(a) <= 160 and (a in known_aliases or normalize(a) in source_text)}),
        }
    for key in ambiguous:
        entities.pop(key, None)
    candidates, rejected, seen = [], [], set()
    known_claims = {claim['id']: claim for claim in (existing_claims or [])}
    for index, claim in enumerate(extraction.claims[:6]):
        subject, target = entities.get(normalize(claim.subject)), entities.get(normalize(claim.object))
        relation = normalize(claim.relation).replace('_', ' ')
        reason = None
        if not subject or not target:
            reason = 'Unknown entity endpoint'
        elif subject['id'] == target['id']:
            reason = 'Self relationship'
        elif not relation or len(relation) > 100 or relation in {'related to', 'relates to', 'associated with', 'connected to', 'mentions', 'references', 'has relation to'}:
            reason = 'Relationship is too vague'
        elif not claim.evidence or any(
            not c.quote.strip() or c.page_number not in page_text
            or c.quote not in page_text[c.page_number] for c in claim.evidence
        ):
            reason = 'Evidence is missing or is not an exact quote from supplied context'
        replaced = known_claims.get(claim.replaces_claim_id) if claim.replaces_claim_id else next((saved for saved in known_claims.values()
            if saved['subject_id'] == subject['id'] and saved['object_id'] == target['id']
            and normalize(saved['relation']) == relation
            and normalize(saved.get('qualifiers') or '') == normalize(claim.qualifiers)), None)
        if not reason and claim.replaces_claim_id and (
            not replaced or replaced['subject_id'] != subject['id'] or replaced['object_id'] != target['id']
        ):
            reason = 'Replacement must identify an existing claim with the same endpoints'
        if reason:
            rejected.append({'index': index, 'reason': reason})
            continue
        claim_id = replaced['id'] if replaced else stable_id(document_id, subject['id'], relation, target['id'], normalize(claim.qualifiers))
        if claim_id in seen:
            # Merge supporting citations instead of dropping later support for a repeated claim.
            previous = next(c for c in candidates if c['id'] == claim_id)
            for c in claim.evidence:
                if c.model_dump() not in previous['evidence']:
                    previous['evidence'].append(c.model_dump())
            continue
        seen.add(claim_id)
        candidates.append({
            'id': claim_id, 'subject': subject, 'relation': relation, 'object': target,
            'qualifiers': claim.qualifiers.strip(), 'evidence': [c.model_dump() for c in claim.evidence],
            'replaces_claim_id': replaced['id'] if replaced else None,
        })
    return candidates, rejected


def prepare_entity_updates(extraction: Extraction, pages: list[dict], registry: list[dict]):
    """Only existing, source-grounded entities can receive standalone details."""
    known = {entity['id']: entity for entity in registry}
    page_text = {page['page_number']: page['content'] for page in pages}
    updates = []
    for update in extraction.entity_updates[:2]:
        detail = update.detail.strip()
        existing = known.get(update.existing_id)
        existing_details = [item['text'] for item in existing.get('details', [])] if existing else []
        if (update.existing_id not in known or not detail or len(detail) > 320
                or (update.replaces_detail and update.replaces_detail not in existing_details)
                or not update.evidence or any(
                    c.page_number not in page_text or not c.quote.strip()
                    or c.quote not in page_text[c.page_number] for c in update.evidence)):
            continue
        if any(item['id'] == update.existing_id for item in updates):
            continue
        updates.append({'id': update.existing_id, 'detail': detail,
                        'replaces_detail': update.replaces_detail,
                        'evidence': [citation.model_dump() for citation in update.evidence]})
    return updates


def prepare_retractions(extraction: Extraction, pages: list[dict], existing_claims: list[dict]):
    """Require a saved claim and exact new source text before considering removal."""
    known = {claim['id']: claim for claim in existing_claims}
    page_text = {page['page_number']: page['content'] for page in pages}
    retractions = []
    for item in extraction.retractions[:2]:
        if (item.existing_id not in known or not item.reason.strip()
                or len(item.reason) > 320 or not item.evidence or any(
                    c.page_number not in page_text or not c.quote.strip()
                    or c.quote not in page_text[c.page_number] for c in item.evidence)):
            continue
        if any(saved['id'] == item.existing_id for saved in retractions):
            continue
        retractions.append({'id': item.existing_id, 'reason': item.reason.strip(),
                            'evidence': [citation.model_dump() for citation in item.evidence]})
    return retractions


def accepted_claims(candidates: list[dict], review: Review):
    """Missing, duplicate, or out-of-range review verdicts never authorize a claim."""
    verdicts = {}
    for verdict in review.verdicts:
        verdicts.setdefault(verdict.index, []).append(verdict)
    return [claim for i, claim in enumerate(candidates)
            if len(verdicts.get(i, [])) == 1 and verdicts[i][0].supported]


def accepted_updates(updates: list[dict], review: Review):
    verdicts = {}
    for verdict in review.update_verdicts:
        verdicts.setdefault(verdict.index, []).append(verdict)
    return [update for i, update in enumerate(updates)
            if len(verdicts.get(i, [])) == 1 and verdicts[i][0].supported]


def accepted_retractions(retractions: list[dict], review: Review):
    verdicts = {}
    for verdict in review.retraction_verdicts:
        verdicts.setdefault(verdict.index, []).append(verdict)
    return [item for i, item in enumerate(retractions)
            if len(verdicts.get(i, [])) == 1 and verdicts[i][0].supported]
