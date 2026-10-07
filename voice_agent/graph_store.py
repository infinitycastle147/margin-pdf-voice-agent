"""Versioned, document-scoped graph storage and a frontend-friendly graph projection."""

import os
import json
from datetime import datetime, timezone
from neo4j import AsyncGraphDatabase
from voice_agent.knowledge import normalize, stable_id


def graph_driver():
    password = os.getenv('NEO4J_PASSWORD')
    if not password:
        raise ValueError('Set NEO4J_PASSWORD before starting the voice agent')
    return AsyncGraphDatabase.driver(
        os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        auth=(os.getenv('NEO4J_USER', 'neo4j'), password),
        connection_timeout=5, max_transaction_retry_time=10,
    )


async def initialize(driver):
    async with driver.session() as session:
        for label in ('KnowledgeEntity', 'KnowledgeClaim', 'KnowledgeEvidence'):
            # Labels are fixed application constants; all content is parameterized.
            result = await session.run(f'CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE')
            await result.consume()


async def entity_registry(tx, document_id):
    result = await tx.run('MATCH (e:KnowledgeEntity {document_id:$doc}) RETURN properties(e) AS entity ORDER BY e.name', doc=document_id)
    entities = []
    async for row in result:
        source = row['entity']
        details = json.loads(source['details_json']) if source.get('details_json') else (
            [{'text': source['detail'], 'evidence': json.loads(source['detail_evidence']) if source.get('detail_evidence') else []}]
            if source.get('detail') else [])
        entities.append({key: source.get(key) for key in ('id', 'name', 'kind', 'aliases', 'updated_at')} | {'details': details})
    return entities


async def claim_registry(tx, document_id):
    result = await tx.run('''
        MATCH (c:KnowledgeClaim {document_id:$doc})-[:SUBJECT]->(s:KnowledgeEntity)
        MATCH (c)-[:OBJECT]->(o:KnowledgeEntity)
        OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(e:KnowledgeEvidence)
        RETURN c.id AS id, s.id AS subject_id, s.name AS subject,
               o.id AS object_id, o.name AS object, c.relation AS relation,
               c.qualifiers AS qualifiers,
               collect(DISTINCT e{.page_number,.quote}) AS evidence ORDER BY c.updated_at DESC
    ''', doc=document_id)
    return [dict(row) async for row in result]


async def read_vocabulary(tx, document_id):
    predicates = await tx.run(
        'MATCH (c:KnowledgeClaim {document_id:$doc}) RETURN DISTINCT c.relation AS relation ORDER BY relation',
        doc=document_id)
    relations = [row['relation'] async for row in predicates]
    return {'relations': relations}


async def write_knowledge(tx, state):
    """Atomically apply a small reviewed patch to the document graph."""
    doc = state['document_id']
    now = datetime.now(timezone.utc).isoformat()
    claims = state.get('claims', [])
    updates = state.get('entity_updates', [])
    retractions = state.get('retractions', [])
    if not claims and not updates and not retractions:
        return {'saved_claims': 0, 'updated_entities': 0, 'retracted_claims': 0, 'document_id': doc}
    for update in updates:
        result = await tx.run('''
            MATCH (e:KnowledgeEntity {id:$id, document_id:$doc})
            RETURN properties(e) AS entity
        ''', id=update['id'], doc=doc)
        record = await result.single()
        if record is None:
            raise ValueError('Entity update target no longer exists')
        old = record['entity']
        details = json.loads(old['details_json']) if old.get('details_json') else (
            [{'text': old['detail'], 'evidence': json.loads(old['detail_evidence']) if old.get('detail_evidence') else []}]
            if old.get('detail') else [])
        replacement = update.get('replaces_detail')
        if replacement:
            if replacement not in {item['text'] for item in details}:
                raise ValueError('Entity detail to correct no longer exists')
            details = [item for item in details if item['text'] != replacement]
        if not any(normalize(item['text']) == normalize(update['detail']) for item in details):
            details.append({'text': update['detail'], 'evidence': update['evidence']})
        result = await tx.run('''
            MATCH (e:KnowledgeEntity {id:$id, document_id:$doc})
            SET e.details_json=$details, e.detail=null, e.detail_evidence=null, e.updated_at=$now
        ''', id=update['id'], doc=doc, details=json.dumps(details), now=now)
        await result.consume()
    for claim in claims:
        for entity in (claim['subject'], claim['object']):
            result = await tx.run('''
                MERGE (e:KnowledgeEntity {id:$id})
                ON CREATE SET e.created_at=$now, e.aliases=[]
                SET e.document_id=$doc, e.name=$name, e.kind=$kind, e.updated_at=$now,
                    e.aliases=reduce(acc=coalesce(e.aliases,[]), a IN $aliases |
                        CASE WHEN a IN acc THEN acc ELSE acc + a END)
            ''', **entity, doc=doc, now=now)
            await result.consume()
        if claim.get('replaces_claim_id'):
            result = await tx.run('''
                MATCH (c:KnowledgeClaim {id:$id, document_id:$doc})-[:SUBJECT]->(s:KnowledgeEntity {id:$subject})
                MATCH (c)-[:OBJECT]->(o:KnowledgeEntity {id:$object})
                RETURN c.relation AS relation, c.qualifiers AS qualifiers
            ''', id=claim['id'], doc=doc, subject=claim['subject']['id'], object=claim['object']['id'])
            old = await result.single()
            if old is None:
                raise ValueError('Claim revision target no longer exists')
            if old['relation'] != claim['relation'] or old['qualifiers'] != claim['qualifiers']:
                result = await tx.run('''
                    MATCH (c:KnowledgeClaim {id:$id, document_id:$doc})-[:SUPPORTED_BY]->(e:KnowledgeEvidence)
                    DETACH DELETE e
                ''', id=claim['id'], doc=doc)
                await result.consume()
        result = await tx.run('''
            MATCH (s:KnowledgeEntity {id:$subject, document_id:$doc}),
                  (o:KnowledgeEntity {id:$object, document_id:$doc})
            MERGE (c:KnowledgeClaim {id:$id})
            ON CREATE SET c.created_at=$now
            SET c.document_id=$doc, c.relation=$relation, c.qualifiers=$qualifiers,
                c.updated_at=$now, c.validation='evidence-reviewed', c.version=2
            MERGE (c)-[:SUBJECT]->(s)
            MERGE (c)-[:OBJECT]->(o)
        ''', subject=claim['subject']['id'], object=claim['object']['id'],
            id=claim['id'], doc=doc, relation=claim['relation'], qualifiers=claim['qualifiers'], now=now)
        await result.consume()
        for citation in claim['evidence']:
            evidence_id = stable_id(claim['id'], str(citation['page_number']), citation['quote'])
            result = await tx.run('''
                MATCH (c:KnowledgeClaim {id:$claim})
                MERGE (e:KnowledgeEvidence {id:$id})
                ON CREATE SET e.created_at=$now
                SET e.document_id=$doc, e.page_number=$page, e.quote=$quote
                MERGE (c)-[:SUPPORTED_BY]->(e)
            ''', claim=claim['id'], id=evidence_id, doc=doc, page=citation['page_number'],
                quote=citation['quote'], now=now)
            await result.consume()
    retracted_count = 0
    for item in retractions:
        result = await tx.run('''
            MATCH (c:KnowledgeClaim {id:$id, document_id:$doc})
            OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(e:KnowledgeEvidence)
            WITH c, collect(DISTINCT e) AS evidence
            FOREACH (source IN evidence | DETACH DELETE source)
            DETACH DELETE c
            RETURN 1 AS removed
        ''', id=item['id'], doc=doc)
        retracted_count += 1 if await result.single() else 0
    if retractions:
        result = await tx.run('''
            MATCH (e:KnowledgeEntity {document_id:$doc})
            WHERE NOT (e)<-[:SUBJECT|OBJECT]-(:KnowledgeClaim)
              AND coalesce(e.detail, '') = '' AND coalesce(e.details_json, '[]') = '[]'
            DETACH DELETE e
        ''', doc=doc)
        await result.consume()
    return {'saved_claims': len(claims), 'updated_entities': len(updates),
            'retracted_claims': retracted_count, 'document_id': doc, 'updated_at': now}


async def read_knowledge(tx, document_id):
    nodes = await entity_registry(tx, document_id)
    for node in nodes:
        node['type'] = 'entity'
    result = await tx.run('''
        MATCH (c:KnowledgeClaim {document_id:$doc})-[:SUBJECT]->(s:KnowledgeEntity)
        MATCH (c)-[:OBJECT]->(o:KnowledgeEntity)
        OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(e:KnowledgeEvidence)
        RETURN c{.id,.relation,.qualifiers,.validation,.updated_at} AS claim,
               s.id AS source, o.id AS target,
               collect(DISTINCT e{.page_number,.quote}) AS evidence ORDER BY claim.id
    ''', doc=document_id)
    edges = []
    async for record in result:
        edges.append({**record['claim'], 'source': record['source'], 'target': record['target'],
                      'evidence': sorted(record['evidence'], key=lambda e: (e['page_number'], e['quote'])), 'type': 'claim'})
    # Older sessions saved Concept relationships with quotes, but did not pass
    # the current independent evidence review. Keep them visible and distinct.
    result = await tx.run('''
        MATCH (n:Concept {document_id:$doc})
        RETURN n.key AS key, n.name AS name ORDER BY name, key
    ''', doc=document_id)
    legacy_nodes = [record async for record in result]
    for record in legacy_nodes:
        nodes.append({'id': f'legacy:{document_id}:{record["key"]}',
                      'name': record['name'], 'kind': 'legacy concept', 'type': 'legacy'})
    result = await tx.run('''
        MATCH (a:Concept {document_id:$doc})-[r:RELATED_TO]->(b:Concept {document_id:$doc})
        RETURN a.key AS source, b.key AS target, r.relation AS relation,
               r.page_number AS page_number, r.evidence AS quote
        ORDER BY source, target, relation
    ''', doc=document_id)
    async for record in result:
        source = f'legacy:{document_id}:{record["source"]}'
        target = f'legacy:{document_id}:{record["target"]}'
        evidence = ([{'page_number': record['page_number'], 'quote': record['quote']}]
                    if record['page_number'] and record['quote'] else [])
        edges.append({'id': stable_id(source, target, record['relation'] or '',
                                      str(record['page_number'] or ''), record['quote'] or ''),
                      'source': source, 'target': target,
                      'relation': record['relation'] or 'related to',
                      'type': 'legacy', 'evidence': evidence})
    timestamps = [item['updated_at'] for item in [*nodes, *edges] if item.get('updated_at')]
    return {'document_id': document_id, 'nodes': nodes, 'edges': edges,
            'legacy_entity_count': len(legacy_nodes), 'schema_version': 3,
            'updated_at': max(timestamps, default=None)}
