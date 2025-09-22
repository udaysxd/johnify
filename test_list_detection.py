import sys
sys.path.append('c:/johnify/backend')
from app.mlites import _is_list_type_topic

# Test cases
test_topics = [
    'top 10 companies',
    'best restaurants in New York',
    'largest cities in the world',
    'history of space exploration',
    'how to cook pasta',
    'top 5 movies of 2023',
    'smallest countries',
    'richest people',
    'daily exercise routine'
]

print('Testing _is_list_type_topic function:')
for topic in test_topics:
    result = _is_list_type_topic(topic)
    print(f'Topic: \"{topic}\" -> List-type: {result}')
