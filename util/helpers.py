import html
from bs4 import BeautifulSoup

def clean_html_string(html_str: str) -> str:
    ''' remove html tags and special characters from html '''
    # remove tags
    soup = BeautifulSoup(html_str, "html.parser")
    text_with_entities = soup.get_text()
    
    # remove characters
    cleaned_text = html.unescape(text_with_entities)
    
    return cleaned_text