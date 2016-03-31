def es_query(input_query, doc_type, min_score=0.5, additional_filter=None):
    """wrap the body to filter by doc_type
    as some full text queries seem to break in ElasticSearch
    if, instead, we pass the doc_type in the URL path."""
    query = {
        'query': {
            'filtered': {
                'query': input_query,
                'filter': {
                    'type': {
                        'value': doc_type
                    }
                }
            }
        },
        'min_score': min_score
    }
    return query


def merge_input_queries(must_queries=None, should_queries=None):
    bool_part = {}
    if must_queries is not None:
        bool_part['must'] = must_queries
    if should_queries is not None:
        bool_part['should'] = should_queries
    return {'bool': bool_part}

def add_filter_from_list(query, field, list_ids):
    filtered = {'query': query}
    filtered['filter'] = {
        'terms': {
            field: list_ids
        }
    }
    return {'filtered': filtered}
