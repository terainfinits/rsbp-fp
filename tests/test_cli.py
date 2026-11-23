import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, RDF

from codekg.model import KG

PROJECT = Path(__file__).resolve().parents[1]


class Demo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "demo"
        shutil.copytree(PROJECT / "demo", self.root,
                        ignore=shutil.ignore_patterns("codekg-out", "__pycache__"))

    def invoke(self, *args, ok=True):
        process = subprocess.run([sys.executable, "-m", "codekg.cli", *map(str, args)],
                                 cwd=self.root, capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout, "")
            return process.stderr
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_demo(self):
        stats = self.invoke("build", ".")
        self.assertEqual((stats["symbols"], stats["resolved"], stats["unresolved"]), (8, 3, 1))
        self.assertEqual(stats["errors"], [])
        saves = self.invoke("find", "save", "--root", self.root)
        self.assertEqual({n["qualified"] for n in saves},
                         {"app.service.SessionStore.save", "auth.tokens.TokenStore.save"})
        self.assertEqual(self.invoke("find", "settings.json")[0]["kind"], "File")
        verify = self.invoke("find", "verify_token")[0]["id"]
        calls = self.invoke("callers", verify)
        self.assertEqual([r["siteLine"] for r in calls], [6, 10, 12])
        login = calls[-1]["id"]
        self.assertEqual([(r["id"], r["siteLine"]) for r in self.invoke("callees", login)],
                         [(verify, 10), (verify, 12)])
        query = self.invoke("query", PROJECT / "queries/verify_callers.rq")
        self.assertEqual([(r["caller"], r["path"], r["line"]) for r in query],
                         [(r["id"], r["sitePath"], r["siteLine"]) for r in calls])
        html = (self.root / "codekg-out/graph.html").read_text(encoding="utf-8")
        graph = json.loads(re.search(r'<script id="graph-data"[^>]*>(.*?)</script>', html)[1])
        edge = next(e for e in graph["edges"] if e["source"] == login and e["target"] == verify)
        self.assertEqual([s["line"] for s in edge["evidence"]], [10, 12])
        self.assertTrue(any(e["rel"] == "inheritsFrom" for e in graph["edges"]))
        self.assertTrue(any(e["rel"] == "imports" for e in graph["edges"]))
        rdf = Graph().parse(self.root / "codekg-out/graph.ttl")
        unknown, = rdf.subjects(KG.status, Literal("unresolved"))
        self.assertEqual(str(rdf.value(unknown, KG.expression)), "handlers[action]")
        self.assertIsNone(rdf.value(unknown, KG.target))
        klass = self.invoke("find", "app.service.SessionStore")[0]
        self.assertEqual([n["name"] for n in self.invoke("members", klass["id"])], ["save"])

    def test_rebuild(self):
        self.invoke("build", ".")
        file = self.root / "auth/tokens.py"
        original = self.invoke("find", "verify_token")[0]
        content = file.read_text()
        file.write_text("\n\n" + content)
        self.invoke("build", ".")
        moved = self.invoke("find", "verify_token")[0]
        self.assertEqual(moved["id"], original["id"])
        self.assertEqual(moved["line"], original["line"] + 2)
        file.write_text(content.replace("verify_token", "validate_token"))
        stats = self.invoke("build", ".")
        self.assertFalse(self.invoke("find", "verify_token"))
        self.assertFalse(self.invoke("callers", self.invoke("find", "validate_token")[0]["id"]))
        self.assertEqual(stats["resolved"], 0)

    def test_ignores_and_errors(self):
        (self.root / ".gitignore").write_text("*.log\n!public.log\n")
        (self.root / "app/.gitignore").write_text("private.txt\n")
        for name in ["app/private.txt", "private.log", "public.log"]:
            (self.root / name).touch()
        (self.root / "broken.py").write_text("def invalid(\n")
        self.assertIn("codekg build", self.invoke("find", "save", ok=False))
        stats = self.invoke("build", ".")
        self.assertEqual(stats["errors"][0]["path"], "broken.py")
        self.assertFalse(self.invoke("find", "private"))
        self.assertTrue(self.invoke("find", "public.log"))
        self.assertFalse(self.invoke("find", "codekg-out"))
        query = self.root / "q.rq"
        for text in ["ASK {}", "SELECT * FROM <https://example.org/g> WHERE {?s ?p ?o}",
                     "SELECT * WHERE {SERVICE <https://example.org/g> {?s ?p ?o}}"]:
            query.write_text(text)
            self.invoke("query", query, ok=False)

    def test_scope_and_nested_calls(self):
        (self.root / "app/other.py").write_text(
            "from .service import login as run\n"
            "def direct():\n    return run()()\n"
            "def dynamic(run):\n    return run()\n")
        self.invoke("build", ".")
        login = self.invoke("find", "app.service.login")[0]
        callers = self.invoke("callers", login["id"])
        self.assertEqual([c["qualified"] for c in callers], ["app.other.direct"])
        rdf = Graph().parse(self.root / "codekg-out/graph.ttl")
        sites = [s for s in rdf.subjects(RDF.type, KG.CallSite)
                 if str(rdf.value(s, KG.path)) == "app/other.py"]
        self.assertEqual(len(sites), 3)


if __name__ == "__main__":
    unittest.main()
