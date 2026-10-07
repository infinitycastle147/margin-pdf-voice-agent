"""Opt-in Neo4j integration check; all synthetic fixture writes are rolled back."""
import asyncio
from uuid import uuid4

import database  # Loads the configured local environment, without printing secrets.
from voice_agent.graph_store import graph_driver, read_knowledge, write_knowledge
from voice_agent.knowledge import Extraction, prepare_candidates


async def main():
    doc = 'integration-' + str(uuid4())
    pages = [{'page_number':1,'content':'Acme manufactures turbines. Acme supplies turbines.'}]
    extraction = Extraction.model_validate({'entities':[
        {'name':'Acme','kind':'organization','aliases':['Acme Ltd']},
        {'name':'Turbines','kind':'product'}], 'claims':[
        {'subject':'Acme','relation':'manufactures','object':'Turbines',
         'evidence':[{'page_number':1,'quote':'Acme manufactures turbines.'}]}]})
    claims, _ = prepare_candidates(extraction,pages,[],doc)
    state = {'document_id':doc,'question_id':'test-question','query':'Who makes turbines?',
             'intent':{'topic':'Turbine manufacturing','focus':'Identify manufacturers'},'claims':claims}
    async with graph_driver() as driver:
        async with driver.session() as session:
            tx = await session.begin_transaction()
            try:
                await write_knowledge(tx,state)
                await write_knowledge(tx,state)
                graph = await read_knowledge(tx,doc)
                assert len([n for n in graph['nodes'] if n['type']=='entity']) == 2
                assert len([n for n in graph['nodes'] if n['type']=='topic']) == 0
                edges = [e for e in graph['edges'] if e['type']=='claim']
                assert len(edges) == 1, 'Repeated enrichment duplicated a claim'
                assert edges[0]['evidence'] == [{'page_number':1,'quote':'Acme manufactures turbines.'}]
                revised = {**claims[0], 'relation': 'supplies', 'replaces_claim_id': claims[0]['id'],
                           'evidence': [{'page_number': 1, 'quote': 'Acme supplies turbines.'}]}
                state['claims'] = [revised]
                await write_knowledge(tx,state)
                graph = await read_knowledge(tx,doc)
                edges = [e for e in graph['edges'] if e['type'] == 'claim']
                assert len(edges) == 1 and edges[0]['id'] == claims[0]['id']
                assert edges[0]['relation'] == 'supplies'
                assert edges[0]['evidence'] == [{'page_number': 1, 'quote': 'Acme supplies turbines.'}]
                state['claims'] = []
                state['entity_updates'] = [{'id': claims[0]['subject']['id'],
                    'detail': 'Manufactures turbines.',
                    'evidence': [{'page_number': 1, 'quote': 'Acme manufactures turbines.'}]}]
                await write_knowledge(tx,state)
                graph = await read_knowledge(tx,doc)
                assert next(n for n in graph['nodes'] if n['id'] == claims[0]['subject']['id'])['details'][0]['text'] == 'Manufactures turbines.'
                state['entity_updates'] = [{'id': claims[0]['subject']['id'],
                    'detail': 'Supplies turbines.',
                    'evidence': [{'page_number': 1, 'quote': 'Acme supplies turbines.'}]}]
                await write_knowledge(tx,state)
                state['entity_updates'] = [{'id': claims[0]['subject']['id'],
                    'detail': 'Produces turbines.', 'replaces_detail': 'Manufactures turbines.',
                    'evidence': [{'page_number': 1, 'quote': 'Acme manufactures turbines.'}]}]
                await write_knowledge(tx,state)
                graph = await read_knowledge(tx,doc)
                details = next(n for n in graph['nodes'] if n['id'] == claims[0]['subject']['id'])['details']
                assert {item['text'] for item in details} == {'Supplies turbines.', 'Produces turbines.'}
                state['entity_updates'] = []
                state['retractions'] = [{'id': claims[0]['id'], 'reason': 'Fixture correction',
                    'evidence': [{'page_number': 1, 'quote': 'Acme manufactures turbines.'}]}]
                await write_knowledge(tx,state)
                graph = await read_knowledge(tx,doc)
                assert not [e for e in graph['edges'] if e['type'] == 'claim']
                assert len([n for n in graph['nodes'] if n['type'] == 'entity']) == 1
                isolated = await read_knowledge(tx,doc + '-other')
                assert isolated['nodes'] == [] and isolated['edges'] == []
                result = await tx.run('MATCH (n:Question {document_id:$doc}) RETURN count(n) AS count',doc=doc)
                assert (await result.single())['count'] == 0, 'Raw question became a semantic node'
                print('PASS: Neo4j write/read, deduplication, claim revision, node update, retraction, document isolation. Fixtures rolled back.')
            finally:
                await tx.rollback()


if __name__ == '__main__':
    asyncio.run(main())
