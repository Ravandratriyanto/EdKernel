from pathlib import Path
from dotenv import dotenv_values
KEYS = [('API_KEY', 'LLM provider (Groq)'), ('TAVILY_KEY', 'Tavily search, for past papers')]

def mask(value: str) -> str:
    return '****' + (value[-4:] if len(value) > 4 else '')

def main() -> None:
    env_path = Path(__file__).with_name('.env')
    print('API keys from .env:')
    if not env_path.is_file():
        print('  no .env file - copy .env.example to .env to store keys')
        return
    values = dotenv_values(env_path)
    for name, description in KEYS:
        value = (values.get(name) or '').strip()
        state = mask(value) if value else 'not set'
        print(f'  {name:<11} {state:<10} - {description}')
if __name__ == '__main__':
    main()