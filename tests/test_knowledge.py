import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from voice_agent.activity import ActivityStream
from voice_agent.knowledge import (Extraction, Review, prepare_candidates, prepare_entity_updates,
                                   prepare_retractions, accepted_claims, accepted_updates,
                                   accepted_retractions, stable_id)
from voice_agent.graph import GraphEnricher, gather_page_context


DOC = 'test-document'
PAGES = [{'page_number': 3, 'content': 'Acme manufactures turbines. Turbines reduce emissions under normal operation.'}]


def extraction(**overrides):
    claim = {'subject': 'Acme', 'relation': 'manufactures', 'object': 'Turbines',
             'evidence': [{'page_number': 3, 'quote': 'Acme manufactures turbines.'}]}
    claim.update(overrides)
    return Extraction.model_validate({'entities': [
        {'name': 'Acme', 'kind': 'organization'}, {'name': 'Turbines', 'kind': 'product'}], 'claims': [claim]})


class ValidationTests(unittest.TestCase):
    def test_supported_claim_and_repeat_identity(self):
        first, _ = prepare_candidates(extraction(), PAGES, [], DOC)
        again, _ = prepare_candidates(extraction(relation='MANUFACTURES'), PAGES, [], DOC)
        self.assertEqual(first[0]['id'], again[0]['id'])
        self.assertNotEqual(first[0]['id'], prepare_candidates(extraction(), PAGES, [], 'another-doc')[0][0]['id'])

    def test_wrong_page_and_fabricated_or_changed_quote_are_rejected(self):
        for evidence in ([{'page_number':4,'quote':'Acme manufactures turbines.'}],
                         [{'page_number':3,'quote':'Acme manufactures engines.'}],
                         [{'page_number':3,'quote':'ACME manufactures turbines.'}], []):
            with self.subTest(evidence=evidence):
                candidates, rejected = prepare_candidates(extraction(evidence=evidence), PAGES, [], DOC)
                self.assertFalse(candidates)
                self.assertTrue(rejected)

    def test_vague_and_unbound_relations_are_rejected(self):
        for params in ({'relation':'related_to'}, {'subject':'Unknown'}, {'object':'Acme'}):
            with self.subTest(params=params):
                self.assertFalse(prepare_candidates(extraction(**params), PAGES, [], DOC)[0])

    def test_conditions_are_part_of_claim_identity(self):
        a = prepare_candidates(extraction(qualifiers='Only in 2024'), PAGES, [], DOC)[0][0]
        b = prepare_candidates(extraction(qualifiers='Not in 2024'), PAGES, [], DOC)[0][0]
        self.assertNotEqual(a['id'], b['id'])

    def test_alias_cannot_merge_unrelated_entity(self):
        registry = [{'id':'known-acme','name':'Acme Research','kind':'organization','aliases':['AR']}]
        value = extraction()
        value.entities[0].existing_id = 'known-acme'
        candidate = prepare_candidates(value, PAGES, registry, DOC)[0][0]
        self.assertNotEqual(candidate['subject']['id'], 'known-acme')
        registry[0]['aliases'].append('Acme')
        candidate = prepare_candidates(value, PAGES, registry, DOC)[0][0]
        self.assertEqual(candidate['subject']['id'], 'known-acme')

    def test_semantic_review_rejects_quote_that_does_not_entail_claim(self):
        candidates, _ = prepare_candidates(extraction(relation='owns'), PAGES, [], DOC)
        self.assertEqual(len(candidates), 1)  # Verbatim quotation alone is insufficient.
        review = Review.model_validate({'verdicts':[{'index':0,'supported':False,'reason':'Manufacturing does not establish ownership.'}]})
        self.assertEqual(accepted_claims(candidates, review), [])

    def test_missing_duplicate_and_out_of_range_review_fail_closed(self):
        candidates, _ = prepare_candidates(extraction(), PAGES, [], DOC)
        yes = {'index':0,'supported':True,'reason':'Explicit source statement.'}
        for verdicts in ([], [yes,yes], [{**yes,'index':9}]):
            self.assertFalse(accepted_claims(candidates, Review.model_validate({'verdicts':verdicts})))
        self.assertEqual(accepted_claims(candidates, Review.model_validate({'verdicts':[yes]})), candidates)

    def test_duplicate_claim_accumulates_supporting_quotes(self):
        value = extraction()
        value.claims.append(value.claims[0].model_copy(update={'evidence':value.claims[0].evidence}))
        candidates, _ = prepare_candidates(value, PAGES, [], DOC)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]['evidence']), 1)

    def test_relation_revision_keeps_claim_identity_and_requires_matching_endpoints(self):
        original = prepare_candidates(extraction(), PAGES, [], DOC)[0][0]
        old = [{'id': original['id'], 'subject_id': original['subject']['id'],
                'object_id': original['object']['id'], 'relation': 'manufactures', 'qualifiers': ''}]
        revised = extraction(relation='supplies', replaces_claim_id=original['id'])
        candidate, rejected = prepare_candidates(revised, PAGES, [], DOC, old)
        self.assertFalse(rejected)
        self.assertEqual(candidate[0]['id'], original['id'])
        self.assertEqual(candidate[0]['relation'], 'supplies')
        old[0]['object_id'] = 'different-entity'
        self.assertFalse(prepare_candidates(revised, PAGES, [], DOC, old)[0])

    def test_existing_revised_claim_is_reused_without_explicit_id(self):
        entity_a = stable_id(DOC, 'organization', 'acme')
        entity_b = stable_id(DOC, 'product', 'turbines')
        old = [{'id': 'prior-revision-id', 'subject_id': entity_a, 'object_id': entity_b,
                'relation': 'manufactures', 'qualifiers': ''}]
        candidate, _ = prepare_candidates(extraction(), PAGES, [], DOC, old)
        self.assertEqual(candidate[0]['id'], 'prior-revision-id')

    def test_single_entity_update_requires_existing_node_and_exact_evidence(self):
        registry = [{'id': 'known-acme', 'name': 'Acme', 'kind': 'organization', 'aliases': []}]
        value = Extraction.model_validate({'entity_updates': [{
            'existing_id': 'known-acme', 'detail': 'Manufactures turbines.',
            'evidence': [{'page_number': 3, 'quote': 'Acme manufactures turbines.'}]}]})
        updates = prepare_entity_updates(value, PAGES, registry)
        self.assertEqual(len(updates), 1)
        self.assertEqual(accepted_updates(updates, Review.model_validate({'update_verdicts': [
            {'index': 0, 'supported': True, 'reason': 'Direct statement'}]})), updates)
        self.assertFalse(accepted_updates(updates, Review()))
        self.assertFalse(prepare_entity_updates(value, PAGES, []))
        value.entity_updates[0].evidence[0].quote = 'Fabricated quote'
        self.assertFalse(prepare_entity_updates(value, PAGES, registry))
        registry[0]['details'] = [{'text': 'Makes engines.', 'evidence': []}]
        value.entity_updates[0].evidence[0].quote = 'Acme manufactures turbines.'
        value.entity_updates[0].replaces_detail = 'Makes engines.'
        self.assertEqual(prepare_entity_updates(value, PAGES, registry)[0]['replaces_detail'], 'Makes engines.')
        value.entity_updates[0].replaces_detail = 'Unknown detail.'
        self.assertFalse(prepare_entity_updates(value, PAGES, registry))

    def test_retraction_requires_saved_claim_exact_quote_and_review(self):
        old = [{'id': 'old-claim', 'subject_id': 'a', 'object_id': 'b',
                'relation': 'supplies', 'qualifiers': ''}]
        value = Extraction.model_validate({'retractions': [{
            'existing_id': 'old-claim', 'reason': 'Source contradicts the saved claim.',
            'evidence': [{'page_number': 3, 'quote': 'Acme manufactures turbines.'}]}]})
        candidates = prepare_retractions(value, PAGES, old)
        self.assertEqual(len(candidates), 1)
        self.assertFalse(accepted_retractions(candidates, Review()))
        approved = Review.model_validate({'retraction_verdicts': [
            {'index': 0, 'supported': True, 'reason': 'Direct contradiction.'}]})
        self.assertEqual(accepted_retractions(candidates, approved), candidates)
        self.assertFalse(prepare_retractions(value, PAGES, []))
        value.retractions[0].evidence[0].quote = 'No such source text'
        self.assertFalse(prepare_retractions(value, PAGES, old))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def make_worker(self):
        # No API credentials or network calls in these tests.
        with patch('voice_agent.graph.graph_driver'), patch('voice_agent.graph.genai.Client'):
            return GraphEnricher(DOC, 'test-only', ActivityStream())

    async def test_tool_result_keeps_original_question_after_new_utterance(self):
        worker = self.make_worker()
        worker.observe_query('Who manufactures turbines?')
        first = worker.capture_question()
        worker.observe_query('What about emissions?')
        worker.observe_tool_result({'document_id':DOC,'page_number':3,'content':PAGES[0]['content']}, first)
        event = worker.queue.get_nowait()
        self.assertEqual(event.context.query, 'Who manufactures turbines?')
        self.assertNotEqual(event.context.question_id, worker.current.question_id)

    async def test_query_alone_does_not_create_graph_work(self):
        worker = self.make_worker()
        worker.observe_query('What about it?')
        self.assertTrue(worker.queue.empty())

    async def test_followup_history_includes_previous_answer(self):
        worker = self.make_worker()
        worker.observe_query('Who makes turbines?')
        worker.observe_answer('Acme manufactures turbines.')
        worker.observe_query('What does it make?')
        self.assertEqual(worker.capture_question().history[-2]['text'], 'Acme manufactures turbines.')

    async def test_pipeline_runs_validation_before_persistence(self):
        worker = self.make_worker()
        order = []
        updates = {'context':{'pages':PAGES,'registry':[]},'interpret':{'intent':{'topic':'Turbine manufacturing','focus':'Manufacturer'}},
                   'extract':{'candidates':[{'id':'candidate'}]},'validate':{'claims':[]},'persist':{'saved':{'saved_claims':0}}}
        for name in updates:
            async def stage(state, name=name):
                order.append(name)
                if name == 'persist':
                    self.assertEqual(state['claims'], [])
                return updates[name]
            setattr(worker, '_' + name, stage)
        await worker.graph.ainvoke({'document_id':DOC,'question_id':'q','query':'test','history':[],'tool_results':[]})
        self.assertEqual(order, ['context','interpret','extract','validate','persist'])

    async def test_context_expands_hit_to_original_page_and_neighbors(self):
        rows = [SimpleNamespace(page_number=n, content=f'Page {n} complete surrounding explanation.') for n in (2,3,4)]
        with patch('voice_agent.graph.SessionLocal') as session:
            session.return_value.__enter__.return_value.scalars.return_value.all.return_value=rows
            pages, info = gather_page_context(DOC,[{'document_id':DOC,'matches':[{'page_number':3,'context':'explanation'}]}])
        self.assertEqual({p['page_number'] for p in pages},{2,3,4})
        self.assertEqual(pages[0]['content'], rows[1].content)
        self.assertEqual(info['omitted_retrieved_pages'], [])

    async def test_context_limits_report_omitted_and_windowed_pages(self):
        rows=[SimpleNamespace(page_number=n,content='x'*20000) for n in range(1,30)]
        hits=[{'page_number':n,'context':'x'*50} for n in range(1,20)]
        with patch('voice_agent.graph.SessionLocal') as session:
            session.return_value.__enter__.return_value.scalars.return_value.all.return_value=rows
            pages,info=gather_page_context(DOC,[{'document_id':DOC,'matches':hits}])
        self.assertLessEqual(sum(len(p['content']) for p in pages),70000)
        self.assertTrue(info['windowed_pages'])
        self.assertTrue(info['omitted_retrieved_pages'])


if __name__ == '__main__':
    unittest.main()
