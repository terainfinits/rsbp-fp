import json
from collections import defaultdict
from importlib.resources import files

from rdflib import RDF

from .model import KG, KINDS, RELATIONS


def render(graph):
    nodes = []
    for kind in KINDS:
        for key in graph.subjects(RDF.type, KG[kind]):
            nodes.append(dict(id=str(key), kind=kind, name=str(graph.value(key, KG.name)),
                              label=str(graph.value(key, KG.qualified)),
                              path=str(graph.value(key, KG.path)),
                              line=str(graph.value(key, KG.line) or "")))
    sites = defaultdict(list)
    for site in graph.subjects(RDF.type, KG.CallSite):
        target = graph.value(site, KG.target)
        if target:
            pair = (graph.value(site, KG.caller), target)
            sites[pair].append(dict(path=str(graph.value(site, KG.path)),
                                    line=int(graph.value(site, KG.line)),
                                    column=int(graph.value(site, KG.column))))
    edges = []
    for rel in RELATIONS:
        for source, target in graph.subject_objects(KG[rel]):
            evidence = sites[source, target] if rel == "calls" else []
            edges.append(dict(source=str(source), target=str(target), rel=rel,
                              evidence=sorted(evidence, key=lambda row: (row["line"], row["column"]))))
    data = dict(nodes=sorted(nodes, key=lambda row: row["id"]),
                edges=sorted(edges, key=lambda row: (row["source"], row["rel"], row["target"])))
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    return files("codekg").joinpath("viewer.html").read_text(encoding="utf-8").replace("__DATA__", payload)
