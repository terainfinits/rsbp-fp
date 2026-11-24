from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef

KG = Namespace("urn:codekg:vocab:")
KINDS = ("Folder", "File", "Class", "Function", "Method", "Constant")
RELATIONS = ("contains", "declares", "imports", "inheritsFrom", "calls", "reads")


def identifier(kind, path, name=""):
    parts = [kind, quote(path, safe="/")]
    if name:
        parts.append(quote(name, safe="."))
    return URIRef("urn:codekg:" + ":".join(parts))


def new_graph():
    graph = Graph()
    graph.bind("kg", KG)
    for kind in (*KINDS, "CallSite", "ReadSite"):
        graph.add((KG[kind], RDF.type, RDFS.Class))
    for relation in (*RELATIONS, "caller", "reader", "target", "path", "name", "qualified",
                     "line", "endLine", "column", "expression", "status"):
        graph.add((KG[relation], RDF.type, RDF.Property))
    graph.add((KG.Method, RDFS.subClassOf, KG.Function))
    return graph


def entity(graph, key, kind, path, name, qualified, node=None):
    graph.add((key, RDF.type, KG[kind]))
    for prop, value in [(KG.path, path), (KG.name, name), (KG.qualified, qualified)]:
        graph.add((key, prop, Literal(value)))
    if node is not None:
        graph.add((key, KG.line, Literal(node.lineno)))
        graph.add((key, KG.endLine, Literal(node.end_lineno)))
    return key
