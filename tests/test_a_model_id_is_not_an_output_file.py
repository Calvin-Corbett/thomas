"""A model id in the task is not a file the run must produce (2026-09-06).

The lanes ask named the local models by their Hugging Face ids. The contract's
path rule read "damo-vilab/text-to-video-ms-1.7b" as a path with the extension
".7b" and demanded that it exist and be non-empty in the workspace when the
work was done; it never could, and the run looped on a requirement nobody set.
A path token is an output only when its extension is a real file extension.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core import acceptance_contract as ac


def _outputs(text: str, ws: Path) -> list[str]:
    items = ac.build_contract(text, ws)
    return [i.item_id for i in items if i.kind == ac.KIND_OUTPUT_PATH]


def test_hugging_face_ids_are_not_outputs(tmp_path: Path) -> None:
    text = (
        "Use diffusers with stabilityai/sd-turbo for images, facebook/musicgen-small for music and "
        "damo-vilab/text-to-video-ms-1.7b for video; models are in the cache."
    )
    assert _outputs(text, tmp_path) == []


def test_a_real_file_path_is_still_an_output(tmp_path: Path) -> None:
    assert _outputs("Write the findings to report/summary.md and the raw rows to data/rows.csv", tmp_path) == [
        "output:report/summary.md",
        "output:data/rows.csv",
    ]


def test_a_version_in_a_name_is_not_an_extension(tmp_path: Path) -> None:
    text = (
        "Pin meta-llama/Llama-3.1-8B-Instruct, Qwen/Qwen2.5-7B and nvidia/parakeet-tdt-0.6b; the notes are under "
        "releases/v2.5 upstream and the old settings in config/settings.v2."
    )
    assert _outputs(text, tmp_path) == []


# Only a version or a model size stops being an output. The first fix (2026-09-06, never landed) kept a path only when
# its extension was on a list, which dropped real files whose extension the list lacked; every one of these, absent, is
# still an output, whatever case its extension is in.
_STILL_OUTPUTS = (
    "src/App.vue", "src/Card.svelte", "app/Main.kt", "jobs/Etl.scala", "native/fast.cc", "styles/site.scss",
    "notebooks/explore.ipynb", "logs/events.jsonl", "config/.env.local", "out/model-2.0.json", "docs/guide.pdf",
    "media/intro.mp4", "models/tiny.gguf", "dist/site.tar.gz", "assets/Logo.PNG", "dist/site-1.7z",
    "print/part-2.3mf", "prisma/schema.prisma", "tools/go.mod", "tools/go.sum", "docker/Dockerfile.prod",
    "config/.env.test", "config/.env.prod", "config/.env.staging", "src/App.csproj", "build/Thomas.sln",
    "web/web.config", "ui/MainWindow.xaml", "infra/prod.tfvars", "infra/main.hcl", "nix/shell.nix",
    "cad/bracket.scad", "print/part.gcode", "cad/part.step", "features/login.feature", "locale/fr.po",
    "docs/README.markdown", "man/thomas.1", "lib/libssl.so.3", "requirements/base.in", "templates/page.jinja2",
    "templates/page.tpl", "data/app.sqlite3", "docs/flow.mmd", "docs/seq.puml", "docs/graph.dot",
    "systemd/thomas.timer", "src/fast.cxx", "sketch/blink.ino", "kernels/add.cu", "styles/site.styl",
    "Views/Index.cshtml", "Pages/Index.razor", "pkg/thomas.gemspec", "project/build.sbt", "tools/defs.bzl",
    "build/BUILD.bazel", "logs/session.har", "schemas/event.avro", "data/rows.orc", "dist/thomas.deb",
    "dist/thomas.rpm", "keys/id_ed25519.pub", "certs/client.p12", "certs/client.pfx", "game/project.godot",
    "game/theme.tres", "Assets/Main.unity", "src/fast.hxx", "src/fast.hh", "dist/site.tar.lz4",
)  # fmt: skip


def test_every_kind_of_file_a_task_makes_is_still_an_output(tmp_path: Path) -> None:
    text = "Write " + ", ".join(_STILL_OUTPUTS) + " when the work is done."
    assert _outputs(text, tmp_path) == [f"output:{path}" for path in _STILL_OUTPUTS]
