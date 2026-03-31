# Contributing to Ghost Narrator

Thank you for your interest in contributing to Ghost Narrator!

## How to Contribute

### Reporting Bugs

1. **Check existing issues** - Search for similar bugs before creating a new one
2. **Create a detailed bug report** including:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Docker version, etc.)
   - Any relevant logs

### Suggesting Features

1. **Open a discussion** - Before creating a feature request, open a GitHub Discussion
2. **Describe the use case** - Why do you need this feature?
3. **Propose a solution** - How should it work?

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/my-feature`
3. **Follow the commit convention**: `type(scope): description`
   - `feat`: New feature
   - `fix`: Bug fix
   - `docs`: Documentation
   - `style`: Code style
   - `refactor`: Code refactoring
   - `test`: Tests
   - `chore`: Maintenance
4. **Write tests** for new functionality
5. **Ensure tests pass** before submitting
6. **Update documentation** if needed
7. **Submit your PR**

## Development Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local testing)
- Git

### Local Development

```bash
# Clone the repository
git clone https://github.com/getsimpledirect/workos-mvp.git
cd workos-mvp/ghost-narrator

# Copy environment template
cp .env.example .env

# Start services
./scripts/init.sh
```

### Running Tests

```bash
cd tts-service
pip install -r requirements.txt
pytest tests/ -v
```

## Code Style

- **Python**: Follow PEP 8, use type hints
- **Shell scripts**: Use `shellcheck` for linting
- **Commit messages**: Conventional Commits format

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
