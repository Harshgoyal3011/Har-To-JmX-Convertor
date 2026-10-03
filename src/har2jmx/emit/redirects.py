"""Choose one execution path for observed HTTP redirect chains.

This is an emission policy, not correlation discovery. Captured redirect hops
can be owned by JMeter's redirect follower or remain explicit HTTP samplers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

from har2jmx.correlate import ExtractorType

_REDIRECTS = {301, 302, 303, 307, 308}
_TRANSPORT_HEADERS = {"host", "content-length", "cookie", "connection"}


@dataclass
class RedirectExecution:
    automatic_targets: set[int] = field(default_factory=set)
    explicit_sources: set[int] = field(default_factory=set)
    location_targets: dict[int, int] = field(default_factory=dict)


def _url(value):
    return urldefrag(value)[0]


def _method(source):
    if int(source.status) == 303:
        return "HEAD" if source.method == "HEAD" else "GET"
    if int(source.status) in {301, 302} and source.method == "POST":
        return "GET"
    return source.method


def redirect_execution(result, replayable_header) -> RedirectExecution:
    requests = result.capture.requests
    owners = {i: n for n, txn in enumerate(result.transactions) for i in txn.request_indices}
    emitted = {i for i in owners if not requests[i].classification.excluded}
    produced = {}
    for correlation in result.correlations:
        if correlation.extractor != ExtractorType.COOKIE_MANAGER:
            produced.setdefault(correlation.producer_index, []).append(correlation)
    parameter_slots = {
        slot.request_index
        for dataset in result.parameterization.datasets
        for column in dataset.columns
        for slot in column.slots
        if getattr(slot, "side", "request") == "request"
    }
    edges = {}
    for source in requests:
        if source.index not in emitted or str(source.status) not in {str(v) for v in _REDIRECTS}:
            continue
        location = source.response.redirect_location
        if not location:
            continue
        target_url = _url(urljoin(source.request.url, location))
        for target in requests[source.index + 1 :]:
            if (
                target.index in emitted
                and _url(target.request.url) == target_url
                and target.method == _method(source)
            ):
                edges[source.index] = target.index
                break

    def headers(request):
        return {
            (name.lower(), value)
            for name, value in request.request.headers
            if replayable_header(name) and name.lower() not in _TRANSPORT_HEADERS
        }

    def safe(source_index, target_index):
        source, target = requests[source_index], requests[target_index]
        # Collapse only directly consecutive, same-transaction GET/HEAD hops.
        # Other methods, per-hop headers, CSV inputs and extractors need explicit
        # samplers. CookieManager itself safely processes cookies at every hop.
        if target_index != source_index + 1 or owners[source_index] != owners[target_index]:
            return False
        if source.method not in {"GET", "HEAD"} or target.method != source.method:
            return False
        if produced.get(source_index) or produced.get(target_index) or target_index in parameter_slots:
            return False
        origin = lambda req: urlsplit(req.request.url)[:2]
        if origin(source) != origin(target) or headers(source) != headers(target):
            return False
        # A later request reusing this target/path needs an explicit owner; do
        # not hide the recorded producer behind an automatically followed hop.
        target_path = target.request.path.rstrip("/")
        for later in requests[target_index + 1 :]:
            if (
                later.index in emitted
                and origin(later) == origin(target)
                and (later.request.path == target_path or later.request.path.startswith(target_path + "/"))
            ):
                return False
        return True

    policy = RedirectExecution()
    incoming = set(edges.values())
    for root in edges.keys() - incoming:
        chain = []
        current = root
        while current in edges:
            target = edges[current]
            chain.append((current, target))
            current = target
        # The follower follows the whole chain. A downstream explicit hop means
        # every earlier hop must also remain explicit, preserving response scope.
        automatic = all(safe(source, target) for source, target in chain)
        for source, target in chain:
            if automatic:
                policy.automatic_targets.add(target)
            else:
                policy.explicit_sources.add(source)
                # Existing accepted Location correlations already own their
                # consumer slots. Preserve their extractors and substitutions.
                if target not in parameter_slots and not any(
                    c.from_redirect for c in produced.get(source, [])
                ):
                    policy.location_targets[target] = source
    return policy


def location_variable(source):
    return f"__har2jmx_redirect_{source}"


def add_location_capture(parent, source, subelement, string_prop, regex_extractor):
    """Transport the actual Location URI to an explicit hop, without token heuristics."""
    variable = location_variable(source)
    for tag, label, script in [
        ("JSR223PreProcessor", "Reset redirect target", f"vars.remove('{variable}')"),
        (
            "JSR223PostProcessor",
            "Read current redirect Location",
            (
                f"def location = vars.get('{variable}')\n"
                f"vars.remove('{variable}')\n"
                "if (location?.startsWith('NOT_FOUND_')) location = null\n"
                "if (prev.getResponseCode() in ['301', '302', '303', '307', '308'] && location) {\n"
                "    def target = prev.getURL().toURI().resolve(location)\n"
                "    if (target.scheme in ['http', 'https'] && target.host) {\n"
                f"        vars.put('{variable}', target.toASCIIString().split('#', 2)[0])\n"
                "    }\n"
                "}\n"
                f"if (!vars.get('{variable}')) {{\n"
                "    prev.setSuccessful(false)\n"
                "    prev.setResponseMessage('Expected redirect Location was not produced')\n"
                "    prev.setStopThread(true)\n"
                "}"
            ),
        ),
    ]:
        if tag == "JSR223PostProcessor":
            regex_extractor(parent, variable, r"(?m)^[Ll][Oo][Cc][Aa][Tt][Ii][Oo][Nn]:[ \t]*([^\r\n]+)", True)
        node = subelement(
            parent, tag, {"guiclass": "TestBeanGUI", "testclass": tag, "testname": label, "enabled": "true"}
        )
        for key, value in [
            ("scriptLanguage", "groovy"),
            ("parameters", ""),
            ("filename", ""),
            ("cacheKey", "true"),
            ("script", script),
        ]:
            string_prop(node, key, value)
        subelement(parent, "hashTree")
