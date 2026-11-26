"""Hardened XML parsing: no external entities, no DTDs, no network access."""

from lxml import etree

from invoiceguard.ingestion.errors import ExtractionError


def parse_xml(content: bytes) -> etree._Element:
    """Parse untrusted XML safely and return the root element."""
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=True,
    )
    try:
        return etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ExtractionError(f"invalid XML: {exc}") from exc


def local_name(element: etree._Element) -> str:
    """Tag name without namespace."""
    return etree.QName(element).localname


def xpath_local(path: str) -> str:
    """Relative XPath matching each step by local name (namespace-agnostic)."""
    return "./" + "/".join(f"*[local-name()='{part}']" for part in path.split("/"))


def find_all(element: etree._Element, path: str) -> list[etree._Element]:
    """All elements at ``path`` (slash-separated local names)."""
    result = element.xpath(xpath_local(path))
    if not isinstance(result, list):  # pragma: no cover - xpath on elements returns lists
        return []
    return [node for node in result if isinstance(node, etree._Element)]


def find_text(element: etree._Element, path: str) -> str | None:
    """Stripped text of the first element at ``path``, or ``None``."""
    nodes = find_all(element, path)
    if not nodes or nodes[0].text is None:
        return None
    value = nodes[0].text.strip()
    return value or None
