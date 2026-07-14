from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.dom import minidom
from xml.etree.ElementTree import Comment, Element, SubElement, tostring

from app.models import CorrelationRule, DataEntity, Parameter, SamplerModel
from app.paths import OUTPUT_DIR
from app.patterns import CLASSIFICATION_LABELS, EXTRACTOR_LABELS
from app.utils import apply_variable, xml_safe_comment_text


def jmeter_prop(parent: Element, name: str, value: str = "") -> Element:
    el = SubElement(parent, "stringProp", {"name": name})
    el.text = value
    return el


def bool_prop(parent: Element, name: str, value: bool) -> Element:
    el = SubElement(parent, "boolProp", {"name": name})
    el.text = "true" if value else "false"
    return el


def int_prop(parent: Element, name: str, value: int) -> Element:
    el = SubElement(parent, "intProp", {"name": name})
    el.text = str(value)
    return el


def element_prop(parent: Element, name: str, element_type: str) -> Element:
    return SubElement(parent, "elementProp", {"name": name, "elementType": element_type})


def collection_prop(parent: Element, name: str) -> Element:
    return SubElement(parent, "collectionProp", {"name": name})


def add_test_plan(root: Element, test_name: str, parameters: list[Parameter], config: dict[str, str]) -> Element:
    tree = SubElement(root, "TestPlan", {
        "guiclass": "TestPlanGui",
        "testclass": "TestPlan",
        "testname": test_name,
        "enabled": "true",
    })
    jmeter_prop(tree, "TestPlan.comments", "Generated from HAR by Self Healing JMeter prototype.")
    bool_prop(tree, "TestPlan.functional_mode", False)
    bool_prop(tree, "TestPlan.serialize_threadgroups", False)
    args = element_prop(tree, "TestPlan.user_defined_variables", "Arguments")
    collection = collection_prop(args, "Arguments.arguments")
    udv_parameters = [p for p in parameters if not p.csv_bound]
    existing = {parameter.name for parameter in udv_parameters}
    for parameter in udv_parameters:
        arg = element_prop(collection, parameter.name, "Argument")
        jmeter_prop(arg, "Argument.name", parameter.name)
        jmeter_prop(arg, "Argument.value", parameter.value)
        jmeter_prop(arg, "Argument.metadata", "=")
        jmeter_prop(arg, "Argument.desc", f"Detected from {parameter.reason}; occurrences: {parameter.occurrences}")
    defaults = [
        ("THREADS", config.get("threads", "1"), "Number of concurrent JMeter users."),
        ("LOOPS", config.get("loops", "1"), "Number of iterations per user."),
        ("RAMP_TIME", config.get("ramp", "1"), "Ramp-up time in seconds."),
    ]
    for name, value, desc in defaults:
        if name not in existing:
            arg = element_prop(collection, name, "Argument")
            jmeter_prop(arg, "Argument.name", name)
            jmeter_prop(arg, "Argument.value", value)
            jmeter_prop(arg, "Argument.metadata", "=")
            jmeter_prop(arg, "Argument.desc", desc)
    jmeter_prop(tree, "TestPlan.user_define_classpath", "")
    return tree


def add_thread_group(parent_hash: Element, config: dict[str, str]) -> Element:
    group = SubElement(parent_hash, "ThreadGroup", {
        "guiclass": "ThreadGroupGui",
        "testclass": "ThreadGroup",
        "testname": "Stakeholder Demo Users",
        "enabled": "true",
    })
    jmeter_prop(group, "ThreadGroup.on_sample_error", "continue")
    loop = element_prop(group, "ThreadGroup.main_controller", "LoopController")
    bool_prop(loop, "LoopController.continue_forever", False)
    jmeter_prop(loop, "LoopController.loops", "${LOOPS}")
    jmeter_prop(group, "ThreadGroup.num_threads", "${THREADS}")
    jmeter_prop(group, "ThreadGroup.ramp_time", "${RAMP_TIME}")
    bool_prop(group, "ThreadGroup.scheduler", False)
    jmeter_prop(group, "ThreadGroup.duration", "")
    jmeter_prop(group, "ThreadGroup.delay", "")
    return group


def add_cookie_manager(parent_hash: Element, clear_each_iteration: bool = False) -> None:
    manager = SubElement(parent_hash, "CookieManager", {
        "guiclass": "CookiePanel",
        "testclass": "CookieManager",
        "testname": "HTTP Cookie Manager",
        "enabled": "true",
    })
    collection_prop(manager, "CookieManager.cookies")
    bool_prop(manager, "CookieManager.clearEachIteration", clear_each_iteration)
    bool_prop(manager, "CookieManager.controlledByThreadGroup", False)
    jmeter_prop(manager, "CookieManager.policy", "standard")
    SubElement(parent_hash, "hashTree")


def add_cache_manager(parent_hash: Element) -> None:
    manager = SubElement(parent_hash, "CacheManager", {
        "guiclass": "CacheManagerGui",
        "testclass": "CacheManager",
        "testname": "HTTP Cache Manager",
        "enabled": "true",
    })
    bool_prop(manager, "useExpires", True)
    bool_prop(manager, "CacheManager.controlledByThread", False)
    bool_prop(manager, "clearEachIteration", False)
    SubElement(parent_hash, "hashTree")


def add_dns_cache_manager(parent_hash: Element) -> None:
    manager = SubElement(parent_hash, "DNSCacheManager", {
        "guiclass": "DNSCachePanel",
        "testclass": "DNSCacheManager",
        "testname": "DNS Cache Manager",
        "enabled": "true",
    })
    collection_prop(manager, "DNSCacheManager.servers")
    collection_prop(manager, "DNSCacheManager.hosts")
    bool_prop(manager, "DNSCacheManager.clearEachIteration", False)
    bool_prop(manager, "DNSCacheManager.isCustomResolver", False)
    SubElement(parent_hash, "hashTree")


def add_http_defaults(parent_hash: Element, samplers: list[SamplerModel]) -> None:
    domain_counts = Counter(s.domain for s in samplers if s.domain)
    if not domain_counts:
        return
    default_domain, _ = domain_counts.most_common(1)[0]
    protocol = next((s.protocol for s in samplers if s.domain == default_domain), "https")
    defaults = SubElement(parent_hash, "ConfigTestElement", {
        "guiclass": "HttpDefaultsGui",
        "testclass": "ConfigTestElement",
        "testname": "HTTP Request Defaults",
        "enabled": "true",
    })
    element_prop(defaults, "HTTPsampler.Arguments", "Arguments")
    jmeter_prop(defaults, "HTTPSampler.domain", default_domain)
    jmeter_prop(defaults, "HTTPSampler.port", "")
    jmeter_prop(defaults, "HTTPSampler.protocol", protocol)
    jmeter_prop(defaults, "HTTPSampler.contentEncoding", "")
    jmeter_prop(defaults, "HTTPSampler.path", "")
    bool_prop(defaults, "HTTPSampler.image_parser", False)
    bool_prop(defaults, "HTTPSampler.concurrentDwn", False)
    SubElement(parent_hash, "hashTree")


def add_csv_data_set(parent_hash: Element, csv_path: Path, entity: DataEntity) -> None:
    config = SubElement(parent_hash, "CSVDataSet", {
        "guiclass": "TestBeanGUI",
        "testclass": "CSVDataSet",
        "testname": f"Test Data - {entity.name} (CSV Data Set Config)",
        "enabled": "true",
    })
    jmeter_prop(config, "filename", csv_path.name)
    jmeter_prop(config, "fileEncoding", "UTF-8")
    jmeter_prop(config, "variableNames", ",".join(p.name for p in entity.parameters))
    jmeter_prop(config, "delimiter", ",")
    bool_prop(config, "quotedData", False)
    bool_prop(config, "recycle", True)
    bool_prop(config, "stopThread", False)
    jmeter_prop(config, "shareMode", "shareMode.thread")
    SubElement(parent_hash, "hashTree")


def add_all_csv_data_sets(parent_hash: Element, entities: list[DataEntity], csv_paths: dict[str, Path]) -> None:
    for entity in entities:
        csv_path = csv_paths.get(entity.name)
        if csv_path:
            add_csv_data_set(parent_hash, csv_path, entity)


def add_think_time(parent_hash: Element, min_ms: str = "300", max_range_ms: str = "1200") -> None:
    timer = SubElement(parent_hash, "UniformRandomTimer", {
        "guiclass": "UniformRandomTimerGui",
        "testclass": "UniformRandomTimer",
        "testname": "Think Time (Uniform Random Timer)",
        "enabled": "true",
    })
    jmeter_prop(timer, "ConstantTimer.delay", min_ms)
    jmeter_prop(timer, "RandomTimer.range", max_range_ms)
    SubElement(parent_hash, "hashTree")


def add_header_manager(
    parent_hash: Element,
    sampler: SamplerModel,
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
) -> None:
    headers = [
        (n, v) for n, v in sampler.headers
        if n.lower() not in {"cookie", "host", "content-length"} and v
    ]
    if not headers:
        return
    manager = SubElement(parent_hash, "HeaderManager", {
        "guiclass": "HeaderPanel",
        "testclass": "HeaderManager",
        "testname": f"Headers - {sampler.name}",
        "enabled": "true",
    })
    collection = collection_prop(manager, "HeaderManager.headers")
    for name, value in headers:
        header = element_prop(collection, "", "Header")
        jmeter_prop(header, "Header.name", name)
        jmeter_prop(header, "Header.value", apply_variable(value, parameters, correlations))
    SubElement(parent_hash, "hashTree")


def add_http_sampler(
    parent_hash: Element,
    sampler: SamplerModel,
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
) -> Element:
    http = SubElement(parent_hash, "HTTPSamplerProxy", {
        "guiclass": "HttpTestSampleGui",
        "testclass": "HTTPSamplerProxy",
        "testname": sampler.name,
        "enabled": "true",
    })
    args = element_prop(http, "HTTPsampler.Arguments", "Arguments")
    args_collection = collection_prop(args, "Arguments.arguments")
    raw_body = bool(sampler.post_body and not sampler.post_params)
    bool_prop(http, "HTTPSampler.postBodyRaw", raw_body)
    if raw_body:
        arg = element_prop(args_collection, "", "HTTPArgument")
        bool_prop(arg, "HTTPArgument.always_encode", False)
        jmeter_prop(arg, "Argument.name", "")
        jmeter_prop(arg, "Argument.value", apply_variable(sampler.post_body, parameters, correlations))
        jmeter_prop(arg, "Argument.metadata", "=")
    for name, value in sampler.query + sampler.post_params:
        arg = element_prop(args_collection, name, "HTTPArgument")
        bool_prop(arg, "HTTPArgument.always_encode", False)
        jmeter_prop(arg, "Argument.name", name)
        jmeter_prop(arg, "Argument.value", apply_variable(value, parameters, correlations))
        jmeter_prop(arg, "Argument.metadata", "=")
        bool_prop(arg, "HTTPArgument.use_equals", True)
    jmeter_prop(http, "HTTPSampler.domain", sampler.domain)
    jmeter_prop(http, "HTTPSampler.port", sampler.port)
    jmeter_prop(http, "HTTPSampler.protocol", sampler.protocol)
    jmeter_prop(http, "HTTPSampler.contentEncoding", "")
    jmeter_prop(http, "HTTPSampler.path", sampler.path)
    jmeter_prop(http, "HTTPSampler.method", sampler.method)
    bool_prop(http, "HTTPSampler.follow_redirects", True)
    bool_prop(http, "HTTPSampler.auto_redirects", False)
    bool_prop(http, "HTTPSampler.use_keepalive", True)
    bool_prop(http, "HTTPSampler.DO_MULTIPART_POST", False)
    jmeter_prop(http, "HTTPSampler.embedded_url_re", "")
    jmeter_prop(http, "HTTPSampler.connect_timeout", "")
    jmeter_prop(http, "HTTPSampler.response_timeout", "")
    return http


def add_regex_extractor(
    parent_hash: Element,
    rule: CorrelationRule,
    default_override: str | None = None,
    testname_suffix: str = "",
) -> None:
    extractor = SubElement(parent_hash, "RegexExtractor", {
        "guiclass": "RegexExtractorGui",
        "testclass": "RegexExtractor",
        "testname": f"Correlate {rule.variable}{testname_suffix}",
        "enabled": "true",
    })
    jmeter_prop(extractor, "RegexExtractor.useHeaders", "true" if rule.field == "headers" else "false")
    jmeter_prop(extractor, "RegexExtractor.refname", rule.variable)
    jmeter_prop(extractor, "RegexExtractor.regex", rule.pattern)
    jmeter_prop(extractor, "RegexExtractor.template", "$1$")
    jmeter_prop(extractor, "RegexExtractor.default", default_override if default_override is not None else f"NOT_FOUND_{rule.variable}")
    jmeter_prop(extractor, "RegexExtractor.match_number", "1")
    SubElement(parent_hash, "hashTree")


def add_json_extractor(parent_hash: Element, rule: CorrelationRule) -> None:
    extractor = SubElement(parent_hash, "JSONPostProcessor", {
        "guiclass": "JSONPostProcessorGui",
        "testclass": "JSONPostProcessor",
        "testname": f"Correlate {rule.variable} (JSON)",
        "enabled": "true",
    })
    json_key = rule.json_key or rule.variable
    json_path_expr = f"$.{json_key}" if "." in json_key else f"$..{json_key}"
    jmeter_prop(extractor, "JSONPostProcessor.referenceNames", rule.variable)
    jmeter_prop(extractor, "JSONPostProcessor.jsonPathExprs", json_path_expr)
    jmeter_prop(extractor, "JSONPostProcessor.match_numbers", "1")
    jmeter_prop(extractor, "JSONPostProcessor.defaultValues", f"NOT_FOUND_{rule.variable}")
    SubElement(parent_hash, "hashTree")


def add_css_extractor(parent_hash: Element, rule: CorrelationRule) -> None:
    field_name = rule.json_key or rule.variable
    extractor = SubElement(parent_hash, "HtmlExtractor", {
        "guiclass": "HtmlExtractorGui",
        "testclass": "HtmlExtractor",
        "testname": f"Correlate {rule.variable} (CSS Selector)",
        "enabled": "true",
    })
    jmeter_prop(extractor, "HtmlExtractor.refname", rule.variable)
    jmeter_prop(extractor, "HtmlExtractor.expr", f"input[name='{field_name}']")
    jmeter_prop(extractor, "HtmlExtractor.attribute", "value")
    jmeter_prop(extractor, "HtmlExtractor.match_number", "1")
    jmeter_prop(extractor, "HtmlExtractor.default", f"NOT_FOUND_{rule.variable}")
    SubElement(parent_hash, "hashTree")


def add_correlation_extractor(parent_hash: Element, rule: CorrelationRule) -> None:
    classification_label = CLASSIFICATION_LABELS.get(rule.classification, "Runtime Object Identifier")
    consumer_count = len(rule.consumers)
    consumer_preview = ", ".join(rule.consumers[:3]) + (f" (+{consumer_count - 3} more)" if consumer_count > 3 else "")
    comment = Comment(xml_safe_comment_text(
        f" Correlation: {rule.variable} | classification: {rule.classification} ({classification_label}) | "
        f"origin: {rule.origin} | confidence: {rule.confidence} | reason: {rule.reason} | "
        f"consumed by ({consumer_count}): {consumer_preview} | "
        f"iteration-safe: yes (source request re-executes every loop, so the value is re-extracted fresh each time) | "
        f"thread-safe: yes (JMeter extractors write to thread-local variables; concurrent virtual users never share this value) | "
        f"extractor: {EXTRACTOR_LABELS.get(rule.extractor, EXTRACTOR_LABELS['regex'])} "
    ))
    parent_hash.append(comment)
    if rule.extractor == "json":
        add_json_extractor(parent_hash, rule)
    elif rule.extractor == "css":
        add_css_extractor(parent_hash, rule)
    else:
        add_regex_extractor(parent_hash, rule)

    if rule.confidence == "Low":
        fallback_comment = Comment(xml_safe_comment_text(
            f" Self-healing fallback for {rule.variable}: confidence was Low, so a second Regex Extractor "
            "runs against the same variable. Its default preserves the primary extractor's result instead of "
            "overwriting it, so this only helps - it never replaces a good value with a failure placeholder. "
        ))
        parent_hash.append(fallback_comment)
        add_regex_extractor(
            parent_hash, rule,
            default_override=f"${{{rule.variable}}}",
            testname_suffix=" (Fallback)",
        )


def add_response_assertion(parent_hash: Element, sampler: SamplerModel) -> None:
    status = str(sampler.status or "")
    if not status.isdigit():
        return
    code = int(status)
    if 200 <= code < 400:
        pattern = r"^[23]\d{2}$"
    else:
        pattern = rf"^{code}$"
    assertion = SubElement(parent_hash, "ResponseAssertion", {
        "guiclass": "AssertionGui",
        "testclass": "ResponseAssertion",
        "testname": f"Assert Response Code - {sampler.name}",
        "enabled": "true",
    })
    collection = collection_prop(assertion, "Asserion.test_strings")
    jmeter_prop(collection, pattern, pattern)
    jmeter_prop(assertion, "Assertion.test_field", "Assertion.response_code")
    bool_prop(assertion, "Assertion.assume_success", False)
    int_prop(assertion, "Assertion.test_type", 1)
    SubElement(parent_hash, "hashTree")


def add_duration_assertion(parent_hash: Element, sampler: SamplerModel) -> None:
    threshold = max(sampler.time_ms * 3, 5000)
    assertion = SubElement(parent_hash, "DurationAssertion", {
        "guiclass": "DurationAssertionGui",
        "testclass": "DurationAssertion",
        "testname": f"Assert Duration - {sampler.name}",
        "enabled": "true",
    })
    jmeter_prop(assertion, "DurationAssertion.duration", str(threshold))
    SubElement(parent_hash, "hashTree")


def add_listener(parent_hash: Element) -> None:
    listener = SubElement(parent_hash, "ResultCollector", {
        "guiclass": "ViewResultsFullVisualizer",
        "testclass": "ResultCollector",
        "testname": "View Results Tree",
        "enabled": "true",
    })
    bool_prop(listener, "ResultCollector.error_logging", False)
    obj = SubElement(listener, "objProp")
    name = SubElement(obj, "name")
    name.text = "saveConfig"
    save = SubElement(obj, "value", {"class": "SampleSaveConfiguration"})
    values = {
        "time": "true", "latency": "true", "timestamp": "true", "success": "true",
        "label": "true", "code": "true", "message": "true", "threadName": "true",
        "dataType": "true", "encoding": "false", "assertions": "true", "subresults": "true",
        "responseData": "false", "samplerData": "false", "xml": "false", "fieldNames": "true",
        "responseHeaders": "false", "requestHeaders": "false", "responseDataOnError": "false",
        "saveAssertionResultsFailureMessage": "true", "assertionsResultsToSave": "0",
        "bytes": "true", "sentBytes": "true", "url": "true", "threadCounts": "true",
        "idleTime": "true", "connectTime": "true",
    }
    for key, value in values.items():
        node = SubElement(save, key)
        node.text = value
    jmeter_prop(listener, "filename", "")
    SubElement(parent_hash, "hashTree")


def build_jmx(
    result_id: str,
    samplers: list[SamplerModel],
    parameters: list[Parameter],
    correlations: list[CorrelationRule],
    config: dict[str, str],
    clear_cookies: bool,
    entities: list[DataEntity] | None = None,
    csv_paths: dict[str, Path] | None = None,
) -> Path:
    entities = entities or []
    csv_paths = csv_paths or {}
    test_name = f"Self Healing HAR Conversion {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    root = Element("jmeterTestPlan", {"version": "1.2", "properties": "5.0", "jmeter": "5.6.3"})
    root_hash = SubElement(root, "hashTree")
    add_test_plan(root_hash, test_name, parameters, config)
    plan_hash = SubElement(root_hash, "hashTree")
    add_thread_group(plan_hash, config)
    thread_hash = SubElement(plan_hash, "hashTree")
    add_http_defaults(thread_hash, samplers)
    add_cookie_manager(thread_hash, clear_cookies)
    add_cache_manager(thread_hash)
    add_dns_cache_manager(thread_hash)
    add_all_csv_data_sets(thread_hash, entities, csv_paths)
    add_think_time(thread_hash)

    current_transaction = None
    transaction_hash = thread_hash
    for index, sampler in enumerate(samplers):
        if sampler.transaction != current_transaction:
            current_transaction = sampler.transaction
            controller = SubElement(thread_hash, "TransactionController", {
                "guiclass": "TransactionControllerGui",
                "testclass": "TransactionController",
                "testname": sampler.transaction,
                "enabled": "true",
            })
            bool_prop(controller, "TransactionController.parent", True)
            bool_prop(controller, "TransactionController.includeTimers", False)
            transaction_hash = SubElement(thread_hash, "hashTree")
        add_http_sampler(transaction_hash, sampler, parameters, correlations)
        sampler_hash = SubElement(transaction_hash, "hashTree")
        add_header_manager(sampler_hash, sampler, parameters, correlations)
        is_last_in_transaction = index == len(samplers) - 1 or samplers[index + 1].transaction != sampler.transaction
        if is_last_in_transaction:
            add_response_assertion(sampler_hash, sampler)
        add_duration_assertion(sampler_hash, sampler)
        for rule in sampler.correlations:
            add_correlation_extractor(sampler_hash, rule)
    rough = tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    path = OUTPUT_DIR / f"self_healing_{result_id}.jmx"
    path.write_bytes(pretty)
    return path
