import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from rdflib import Graph, Literal, RDF, URIRef
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parserutils import CompValue

from .extract import extract
from .model import KG, KINDS
from .view import render

FIELDS = """?id a ?type ; kg:path ?path ; kg:name ?name ; kg:qualified ?qualified .
OPTIONAL { ?id kg:line ?line ; kg:endLine ?endLine }
BIND(STRAFTER(STR(?type), "urn:codekg:vocab:") AS ?kind)"""
SELECT = "SELECT ?id ?kind ?name ?qualified ?path ?line ?endLine "


def rows(graph, query, **bindings):
    result = graph.query(query, initNs={"kg": KG}, initBindings=bindings)
    return [{str(k): (int(v) if isinstance(v, Literal) and type(v.value) is int else str(v))
             for k, v in row.asdict().items()} for row in result]


def local_select(filename):
    prepared = prepareQuery(filename.read_text(encoding="utf-8-sig"), initNs={"kg": KG})
    if prepared.algebra.name != "SelectQuery":
        raise ValueError("Gunakan kueri SELECT.")
    def inspect(value):
        if isinstance(value, CompValue):
            if value.name in {"ServiceGraphPattern", "DatasetClause"}:
                raise ValueError("Gunakan dataset lokal tanpa SERVICE atau FROM.")
            for item in value.values():
                inspect(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                inspect(item)
    inspect(prepared.algebra)
    return prepared


def search(graph, command, argument):
    if command == "query":
        return rows(graph, local_select(Path(argument)))
    if command == "find":
        body = FIELDS + """
        BIND(LCASE(STR(?term)) AS ?needle)
        BIND(LCASE(?name) = ?needle || LCASE(?qualified) = ?needle ||
             LCASE(?path) = ?needle AS ?exact)
        FILTER(?exact || CONTAINS(LCASE(?qualified), ?needle) || CONTAINS(LCASE(?path), ?needle))
        """
        return rows(graph, SELECT + "WHERE {" + body + "} ORDER BY DESC(?exact) ?path ?line ?id",
                    term=Literal(argument))
    key = URIRef(argument)
    if not any((key, RDF.type, KG[k]) in graph for k in KINDS):
        raise ValueError("ID tidak ditemukan. Gunakan codekg find untuk memilih ID.")
    if command == "members":
        return rows(graph, SELECT + "WHERE { ?key kg:contains|kg:declares ?id . " +
                    FIELDS + "} ORDER BY ?path ?line ?id", key=key)
    caller, target = ("?id", "?key") if command == "callers" else ("?key", "?id")
    evidence = ("?site kg:caller " + caller + " ; kg:target " + target +
                " ; kg:path ?sitePath ; kg:line ?siteLine ; kg:column ?siteColumn . ")
    return rows(graph, SELECT + "?sitePath ?siteLine ?siteColumn WHERE {" + evidence +
                FIELDS + "} ORDER BY ?sitePath ?siteLine ?siteColumn", key=key)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="codekg")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").add_argument("root", type=Path)
    for name in ("find", "callers", "callees", "members", "query"):
        action = sub.add_parser(name)
        action.add_argument("argument")
        action.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    output = args.root.resolve() / "codekg-out"
    try:
        if args.command == "build":
            graph, result = extract(output.parent)
            output.mkdir(exist_ok=True)
            with TemporaryDirectory(dir=output) as temp:
                stage = Path(temp)
                graph.serialize(destination=stage / "graph.ttl", format="turtle")
                (stage / "graph.html").write_text(render(graph), encoding="utf-8")
                for name in ("graph.ttl", "graph.html"):
                    (stage / name).replace(output / name)
        else:
            index = output / "graph.ttl"
            if not index.is_file():
                raise ValueError(f'Indeks belum tersedia. Jalankan codekg build "{output.parent}".')
            graph = Graph().parse(index, format="turtle")
            result = search(graph, args.command, args.argument)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"codekg: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
