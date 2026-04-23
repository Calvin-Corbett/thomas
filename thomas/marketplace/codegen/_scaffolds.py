"""Project scaffold templates."""

from __future__ import annotations

import json
from typing import Any

from thomas.marketplace.codegen._types import GeneratedFile


def scaffold_python_cli(name: str, options: dict[str, Any]) -> list[GeneratedFile]:
    """Scaffold a Python CLI project."""
    return [
        GeneratedFile(
            path="pyproject.toml",
            content=f"""[project]
name = "{name}"
version = "0.1.0"
description = "CLI application"

[project.scripts]
{name} = "{name}.cli:main"
""",
            language="toml",
        ),
        GeneratedFile(
            path=f"{name}/__init__.py",
            content=f'"""Package {name}."""\n\n__version__ = "0.1.0"\n',
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/cli.py",
            content='''"""CLI entry point."""

import click


@click.group()
def cli():
    """Main CLI group."""
    pass


@cli.command()
@click.option("--name", prompt="Your name", help="Name to greet.")
def hello(name):
    """Say hello."""
    click.echo(f"Hello {name}!")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
''',
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/tests/__init__.py",
            content="",
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/tests/test_cli.py",
            content=f'''"""Tests for CLI."""

import pytest
from click.testing import CliRunner
from {name}.cli import cli


def test_hello():
    """Test hello command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["hello", "--name", "World"])
    assert result.exit_code == 0
    assert "Hello World!" in result.output
''',
            language="python",
        ),
    ]


def scaffold_fastapi(name: str, options: dict[str, Any]) -> list[GeneratedFile]:
    """Scaffold a FastAPI project."""
    return [
        GeneratedFile(
            path="pyproject.toml",
            content=f"""[project]
name = "{name}"
version = "0.1.0"
description = "FastAPI application"

[project.optional-dependencies]
dev = ["pytest", "httpx"]
""",
            language="toml",
        ),
        GeneratedFile(
            path=f"{name}/__init__.py",
            content=f'"""Package {name}."""\n\n__version__ = "0.1.0"\n',
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/main.py",
            content='''"""FastAPI application."""

from fastapi import FastAPI


app = FastAPI(title="API", version="0.1.0")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Hello World"}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
''',
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/tests/__init__.py",
            content="",
            language="python",
        ),
        GeneratedFile(
            path=f"{name}/tests/test_main.py",
            content=f'''"""Tests for main application."""

import pytest
from fastapi.testclient import TestClient
from {name}.main import app


client = TestClient(app)


def test_root():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Hello World"


def test_health():
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
''',
            language="python",
        ),
    ]


def scaffold_flask(name: str, options: dict[str, Any]) -> list[GeneratedFile]:
    """Scaffold a Flask project."""
    return [
        GeneratedFile(
            path=f"{name}/app.py",
            content='''"""Flask application."""

from flask import Flask, jsonify


app = Flask(__name__)


@app.route("/")
def root():
    """Root endpoint."""
    return jsonify({"message": "Hello World"})


@app.route("/health")
def health():
    """Health check."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
''',
            language="python",
        ),
    ]


def scaffold_react(name: str, options: dict[str, Any]) -> list[GeneratedFile]:
    """Scaffold a React project."""
    return [
        GeneratedFile(
            path="package.json",
            content=json.dumps(
                {
                    "name": name,
                    "version": "0.1.0",
                    "private": True,
                    "dependencies": {
                        "react": "^18.0.0",
                        "react-dom": "^18.0.0",
                    },
                },
                indent=2,
            ),
            language="json",
        ),
        GeneratedFile(
            path="src/index.jsx",
            content="""import React from 'react';
import ReactDOM from 'react-dom';
import App from './App';

ReactDOM.render(<App />, document.getElementById('root'));
""",
            language="javascript",
        ),
        GeneratedFile(
            path="src/App.jsx",
            content="""import React from 'react';

function App() {
  return (
    <div className="App">
      <h1>Hello World</h1>
    </div>
  );
}

export default App;
""",
            language="javascript",
        ),
    ]


def scaffold_node_api(name: str, options: dict[str, Any]) -> list[GeneratedFile]:
    """Scaffold a Node.js API project."""
    return [
        GeneratedFile(
            path="package.json",
            content=json.dumps(
                {
                    "name": name,
                    "version": "0.1.0",
                    "main": "server.js",
                    "scripts": {
                        "start": "node server.js",
                        "dev": "nodemon server.js",
                    },
                    "dependencies": {
                        "express": "^4.18.0",
                    },
                },
                indent=2,
            ),
            language="json",
        ),
        GeneratedFile(
            path="server.js",
            content="""const express = require('express');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

app.get('/', (req, res) => {
  res.json({ message: 'Hello World' });
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
""",
            language="javascript",
        ),
    ]
