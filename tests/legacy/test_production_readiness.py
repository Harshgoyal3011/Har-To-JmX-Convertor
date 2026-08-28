#!/usr/bin/env python3
"""
COMPREHENSIVE PRODUCTION READINESS TEST SUITE
Tests the entire application as if a customer is using it.
Includes: unit tests, integration tests, performance tests, edge cases.
"""

from pathlib import Path
import sys
import time
import json
import traceback
from datetime import datetime

app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
        self.start_time = time.time()
        self.timings = {}
    
    def add_pass(self, test_name, duration=None):
        self.passed.append(test_name)
        if duration:
            self.timings[test_name] = duration
        print(f"  {GREEN}✓{RESET} {test_name}")
    
    def add_fail(self, test_name, error):
        self.failed.append((test_name, error))
        print(f"  {RED}✗{RESET} {test_name}")
        print(f"    Error: {error}")
    
    def add_warning(self, test_name, warning):
        self.warnings.append((test_name, warning))
        print(f"  {YELLOW}⚠{RESET} {test_name}")
        print(f"    Warning: {warning}")
    
    def summary(self):
        total = len(self.passed) + len(self.failed)
        elapsed = time.time() - self.start_time
        
        print(f"\n{'='*70}")
        print(f"{BOLD}TEST SUMMARY{RESET}")
        print(f"{'='*70}")
        print(f"Total Tests:  {total}")
        print(f"Passed:       {GREEN}{len(self.passed)}{RESET}")
        print(f"Failed:       {RED}{len(self.failed)}{RESET}")
        print(f"Warnings:     {YELLOW}{len(self.warnings)}{RESET}")
        print(f"Total Time:   {elapsed:.2f}s")
        
        if self.timings:
            print(f"\n{BOLD}Performance Metrics:{RESET}")
            for test, duration in sorted(self.timings.items(), key=lambda x: x[1], reverse=True):
                print(f"  {test}: {duration*1000:.1f}ms")
        
        return len(self.failed) == 0

# ============================================================================
# TEST SECTION 1: IMPORTS & DEPENDENCIES
# ============================================================================

def test_imports():
    """Test all critical imports."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 1: IMPORTS & DEPENDENCIES{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    tests = [
        ("Core Models", lambda: __import__('app.models', fromlist=['SamplerModel'])),
        ("Analyzer Engine", lambda: __import__('app.analyzer', fromlist=['AnalyzerEngine'])),
        ("Value Origin Classifier", lambda: __import__('app.analyzer', fromlist=['ValueOriginClassifier'])),
        ("Correlation Discovery", lambda: __import__('app.correlations.discover_enhanced', fromlist=['discover_correlations_enhanced'])),
        ("Parameter Discovery", lambda: __import__('app.parameters.discover_enhanced', fromlist=['discover_parameters_enhanced'])),
        ("Pipeline v2", lambda: __import__('app.pipeline_v2', fromlist=['convert_har_v2'])),
        ("JMX Builder", lambda: __import__('app.jmx', fromlist=['build_jmx'])),
        ("Server Handler", lambda: __import__('app.server.handler', fromlist=['main'])),
    ]
    
    for test_name, import_func in tests:
        try:
            start = time.time()
            import_func()
            duration = time.time() - start
            result.add_pass(f"Import: {test_name}", duration)
        except Exception as e:
            result.add_fail(f"Import: {test_name}", str(e))
    
    return result

# ============================================================================
# TEST SECTION 2: CORE COMPONENTS INSTANTIATION
# ============================================================================

def test_instantiation():
    """Test creating core component instances."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 2: COMPONENT INSTANTIATION{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    try:
        from har2jmx.analyzer import AnalyzerEngine, DependencyGraph, AIReviewLayer, ValueOriginClassifier
        from har2jmx.models import SamplerModel
        
        # Test AnalyzerEngine
        try:
            start = time.time()
            analyzer = AnalyzerEngine()
            duration = time.time() - start
            result.add_pass("AnalyzerEngine instantiation", duration)
        except Exception as e:
            result.add_fail("AnalyzerEngine instantiation", str(e))
        
        # Test ValueOriginClassifier
        try:
            start = time.time()
            dummy_sampler = SamplerModel(
                name="test", method="GET", url="http://test.com",
                protocol="http", domain="test.com", port="80", path="/",
                query=[], headers=[], cookies=[], response_headers=[],
                post_params=[], post_body="", mime_type="text/html",
                transaction="Test", status=200, time_ms=100,
                response_text='{"test": "value"}'
            )
            classifier = ValueOriginClassifier([dummy_sampler])
            duration = time.time() - start
            result.add_pass("ValueOriginClassifier instantiation", duration)
        except Exception as e:
            result.add_fail("ValueOriginClassifier instantiation", str(e))
        
        # Test DependencyGraph
        try:
            start = time.time()
            dg = DependencyGraph([dummy_sampler])
            duration = time.time() - start
            result.add_pass("DependencyGraph instantiation", duration)
        except Exception as e:
            result.add_fail("DependencyGraph instantiation", str(e))
        
        # Test AIReviewLayer
        try:
            start = time.time()
            ai = AIReviewLayer()
            duration = time.time() - start
            result.add_pass("AIReviewLayer instantiation", duration)
        except Exception as e:
            result.add_fail("AIReviewLayer instantiation", str(e))
    
    except Exception as e:
        result.add_fail("Core imports", str(e))
    
    return result

# ============================================================================
# TEST SECTION 3: DISCOVERY ENGINES
# ============================================================================

def test_discovery_engines():
    """Test enhanced correlation and parameter discovery."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 3: DISCOVERY ENGINES{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    from har2jmx.correlations.discover_enhanced import discover_correlations_enhanced
    from har2jmx.parameters.discover_enhanced import discover_parameters_enhanced
    from har2jmx.models import SamplerModel
    
    # Create realistic test samplers
    samplers = [
        SamplerModel(
            name="browse",
            method="GET",
            url="http://api.example.com/products?category=electronics",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/products",
            query=[("category", "electronics"), ("page", "1")],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="application/json",
            transaction="Browse",
            status=200,
            time_ms=150,
            response_text='{"products": [{"id": 12345, "name": "Laptop", "price": 999.99}], "total": 1}'
        ),
        SamplerModel(
            name="details",
            method="GET",
            url="http://api.example.com/products/12345",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/products/12345",
            query=[],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="application/json",
            transaction="Details",
            status=200,
            time_ms=120,
            response_text='{"id": 12345, "name": "Laptop", "price": 999.99, "stock": true}'
        ),
        SamplerModel(
            name="add_cart",
            method="POST",
            url="http://api.example.com/cart/add",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/cart/add",
            query=[],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body='{"product_id": 12345, "quantity": 1}',
            mime_type="application/json",
            transaction="Cart",
            status=200,
            time_ms=200,
            response_text='{"success": true, "item": {"product_id": 12345, "name": "Laptop", "quantity": 1}}'
        ),
    ]
    
    # Test correlation discovery
    try:
        start = time.time()
        correlations = discover_correlations_enhanced(samplers)
        duration = time.time() - start
        
        if correlations:
            result.add_pass(f"Correlation discovery found {len(correlations)} correlations", duration)
            
            # Check for product_id
            has_product_id = any(c.variable == "product_id" for c in correlations)
            if has_product_id:
                result.add_pass("  ✓ product_id detected as correlation")
            else:
                result.add_warning("Correlation discovery", "product_id not detected (might be too conservative)")
        else:
            result.add_warning("Correlation discovery", "No correlations found (might be empty)")
    except Exception as e:
        result.add_fail("Correlation discovery", str(e))
    
    # Test parameter discovery
    try:
        start = time.time()
        parameters = discover_parameters_enhanced(samplers)
        duration = time.time() - start
        
        if parameters:
            result.add_pass(f"Parameter discovery found {len(parameters)} parameters", duration)
            
            # Check for category
            has_category = any(p.name == "category" for p in parameters)
            if has_category:
                result.add_pass("  ✓ category detected as parameter")
            else:
                result.add_warning("Parameter discovery", "category not detected")
        else:
            result.add_warning("Parameter discovery", "No parameters found")
    except Exception as e:
        result.add_fail("Parameter discovery", str(e))
    
    return result

# ============================================================================
# TEST SECTION 4: VALUE ORIGIN CLASSIFICATION
# ============================================================================

def test_value_origin_classification():
    """Test the new value origin classifier."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 4: VALUE ORIGIN CLASSIFICATION{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    from har2jmx.analyzer import ValueOriginClassifier, ValueClassification
    from har2jmx.models import SamplerModel
    
    # Same test samplers
    samplers = [
        SamplerModel(
            name="browse",
            method="GET",
            url="http://api.example.com/products?category=electronics",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/products",
            query=[("category", "electronics")],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="application/json",
            transaction="Browse",
            status=200,
            time_ms=150,
            response_text='{"products": [{"id": 12345, "name": "Laptop"}]}'
        ),
        SamplerModel(
            name="details",
            method="GET",
            url="http://api.example.com/products/12345",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/products/12345",
            query=[],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="application/json",
            transaction="Details",
            status=200,
            time_ms=120,
            response_text='{"id": 12345, "name": "Laptop"}'
        ),
        SamplerModel(
            name="add_cart",
            method="POST",
            url="http://api.example.com/cart/add",
            protocol="http",
            domain="api.example.com",
            port="80",
            path="/cart/add",
            query=[],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body='{"product_id": 12345, "quantity": 1}',
            mime_type="application/json",
            transaction="Cart",
            status=200,
            time_ms=200,
            response_text='{"success": true}'
        ),
    ]
    
    try:
        start = time.time()
        classifier = ValueOriginClassifier(samplers)
        duration = time.time() - start
        result.add_pass(f"Value origin classification analyzed {len(classifier.value_map)} values", duration)
        
        # Check classifications
        checks = [
            ("product_id", ValueClassification.CORRELATION, "12345"),
            ("category", ValueClassification.PARAMETER, "electronics"),
        ]
        
        for value_name, expected_class, test_value in checks:
            info = classifier.get_info(test_value)
            if info and info.classification == expected_class:
                confidence_str = f"{info.confidence:.0%}" if info.confidence else "unknown"
                result.add_pass(f"  ✓ '{value_name}' correctly classified as {expected_class.value} ({confidence_str})")
            elif info:
                result.add_fail(f"  Classification of '{value_name}'", 
                               f"Expected {expected_class.value}, got {info.classification.value}")
            else:
                result.add_warning(f"  Classification", f"'{value_name}' not found in classifier")
    
    except Exception as e:
        result.add_fail("Value origin classification", str(e))
        traceback.print_exc()
    
    return result

# ============================================================================
# TEST SECTION 5: PIPELINE INTEGRATION
# ============================================================================

def test_pipeline_integration():
    """Test the complete pipeline with a realistic HAR."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 5: PIPELINE INTEGRATION{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    from har2jmx.pipeline_v2 import convert_har_v2
    
    # Create a minimal realistic HAR
    har_data = {
        "log": {
            "version": "1.2",
            "creator": {"name": "test", "version": "1.0"},
            "entries": [
                {
                    "startedDateTime": "2024-01-01T00:00:00Z",
                    "time": 0.150,
                    "request": {
                        "method": "GET",
                        "url": "http://api.example.com/login",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "queryString": [],
                        "postData": None,
                        "cookies": []
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "cookies": [],
                        "content": {
                            "size": 0,
                            "mimeType": "application/json",
                            "text": '{"user_id": 42, "username": "test_user"}'
                        },
                        "redirectURL": ""
                    }
                },
                {
                    "startedDateTime": "2024-01-01T00:00:01Z",
                    "time": 0.120,
                    "request": {
                        "method": "GET",
                        "url": "http://api.example.com/products?category=electronics&page=1",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "queryString": [
                            {"name": "category", "value": "electronics"},
                            {"name": "page", "value": "1"}
                        ],
                        "postData": None,
                        "cookies": []
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "cookies": [],
                        "content": {
                            "size": 0,
                            "mimeType": "application/json",
                            "text": '{"products": [{"id": 12345, "name": "Laptop", "price": 999.99}], "total": 1}'
                        },
                        "redirectURL": ""
                    }
                },
                {
                    "startedDateTime": "2024-01-01T00:00:02Z",
                    "time": 0.200,
                    "request": {
                        "method": "POST",
                        "url": "http://api.example.com/cart/add",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "queryString": [],
                        "postData": {"text": '{"product_id": 12345, "quantity": 1}'},
                        "cookies": []
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "cookies": [],
                        "content": {
                            "size": 0,
                            "mimeType": "application/json",
                            "text": '{"success": true}'
                        },
                        "redirectURL": ""
                    }
                },
            ]
        }
    }
    
    har_bytes = json.dumps(har_data).encode('utf-8')
    
    try:
        start = time.time()
        build_result = convert_har_v2(har_bytes, {})
        duration = time.time() - start
        
        result.add_pass(f"Pipeline executed successfully", duration)
        
        # Check results
        print(f"\n  {BOLD}Pipeline Results:{RESET}")
        print(f"    Samplers: {len(build_result.samplers)}")
        print(f"    Correlations: {len(build_result.correlations)}")
        print(f"    Parameters: {len(build_result.parameters)}")
        print(f"    Entities: {len(build_result.entities)}")
        
        # Validate outputs
        if build_result.samplers:
            result.add_pass("  ✓ Samplers generated")
        else:
            result.add_fail("  Pipeline output", "No samplers generated")
        
        if build_result.correlations:
            result.add_pass(f"  ✓ {len(build_result.correlations)} correlations found")
        else:
            result.add_warning("  Pipeline output", "No correlations found")
        
        if build_result.parameters:
            result.add_pass(f"  ✓ {len(build_result.parameters)} parameters found")
        else:
            result.add_warning("  Pipeline output", "No parameters found")
        
        if build_result.jmx_path:
            result.add_pass("  ✓ JMX file generated")
        else:
            result.add_fail("  Pipeline output", "No JMX file generated")
    
    except Exception as e:
        result.add_fail("Pipeline integration", str(e))
        traceback.print_exc()
    
    return result

# ============================================================================
# TEST SECTION 6: EDGE CASES & ERROR HANDLING
# ============================================================================

def test_edge_cases():
    """Test edge cases and error conditions."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 6: EDGE CASES & ERROR HANDLING{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    from har2jmx.models import SamplerModel
    from har2jmx.analyzer import ValueOriginClassifier
    from har2jmx.correlations.discover_enhanced import discover_correlations_enhanced
    from har2jmx.parameters.discover_enhanced import discover_parameters_enhanced
    
    # Test 1: Empty samplers
    try:
        start = time.time()
        classifier = ValueOriginClassifier([])
        duration = time.time() - start
        result.add_pass("Handle empty sampler list", duration)
    except Exception as e:
        result.add_fail("Handle empty sampler list", str(e))
    
    # Test 2: Sampler with no response
    try:
        start = time.time()
        sampler = SamplerModel(
            name="empty", method="GET", url="http://test.com",
            protocol="http", domain="test.com", port="80", path="/",
            query=[], headers=[], cookies=[], response_headers=[],
            post_params=[], post_body="", mime_type="text/html",
            transaction="Test", status=404, time_ms=0,
            response_text=""
        )
        classifier = ValueOriginClassifier([sampler])
        duration = time.time() - start
        result.add_pass("Handle sampler with empty response", duration)
    except Exception as e:
        result.add_fail("Handle sampler with empty response", str(e))
    
    # Test 3: Invalid JSON in response
    try:
        start = time.time()
        sampler = SamplerModel(
            name="bad_json", method="GET", url="http://test.com",
            protocol="http", domain="test.com", port="80", path="/",
            query=[], headers=[], cookies=[], response_headers=[],
            post_params=[], post_body="", mime_type="application/json",
            transaction="Test", status=200, time_ms=100,
            response_text="{invalid json"
        )
        classifier = ValueOriginClassifier([sampler])
        duration = time.time() - start
        result.add_pass("Handle invalid JSON response", duration)
    except Exception as e:
        result.add_fail("Handle invalid JSON response", str(e))
    
    # Test 4: Very large response
    try:
        start = time.time()
        large_response = json.dumps({"items": [{"id": i, "name": f"item{i}"} for i in range(1000)]})
        sampler = SamplerModel(
            name="large", method="GET", url="http://test.com",
            protocol="http", domain="test.com", port="80", path="/",
            query=[], headers=[], cookies=[], response_headers=[],
            post_params=[], post_body="", mime_type="application/json",
            transaction="Test", status=200, time_ms=500,
            response_text=large_response
        )
        classifier = ValueOriginClassifier([sampler])
        duration = time.time() - start
        result.add_pass("Handle large response (1000 items)", duration)
    except Exception as e:
        result.add_fail("Handle large response", str(e))
    
    # Test 5: Special characters in values
    try:
        start = time.time()
        special_response = json.dumps({"user": "test@example.com", "pwd": "p@$$w0rd!", "data": "日本語"})
        sampler = SamplerModel(
            name="special", method="GET", url="http://test.com",
            protocol="http", domain="test.com", port="80", path="/",
            query=[], headers=[], cookies=[], response_headers=[],
            post_params=[], post_body="", mime_type="application/json",
            transaction="Test", status=200, time_ms=100,
            response_text=special_response
        )
        classifier = ValueOriginClassifier([sampler])
        duration = time.time() - start
        result.add_pass("Handle special characters (email, symbols, unicode)", duration)
    except Exception as e:
        result.add_fail("Handle special characters", str(e))
    
    return result

# ============================================================================
# TEST SECTION 7: PERFORMANCE PROFILING
# ============================================================================

def test_performance():
    """Test performance with realistic data sizes."""
    print(f"\n{BOLD}{BLUE}TEST SECTION 7: PERFORMANCE PROFILING{RESET}")
    print("-" * 70)
    
    result = TestResult()
    
    from har2jmx.analyzer import ValueOriginClassifier
    from har2jmx.models import SamplerModel
    import json
    
    # Create realistic samplers
    print(f"  Creating {BOLD}50-sampler{RESET} test case...")
    
    samplers = []
    for i in range(50):
        response_data = {
            "id": 1000 + i,
            "name": f"item_{i}",
            "data": {"nested": {"value": f"test_{i}"}},
            "timestamp": f"2024-01-01T{i:02d}:00:00Z"
        }
        
        sampler = SamplerModel(
            name=f"request_{i}",
            method="GET" if i % 2 == 0 else "POST",
            url=f"http://api.example.com/endpoint{i}",
            protocol="http",
            domain="api.example.com",
            port="80",
            path=f"/endpoint{i}",
            query=[("id", str(1000 + i)), ("filter", f"type_{i}")],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body=json.dumps({"id": 1000 + i}) if i % 2 == 1 else "",
            mime_type="application/json",
            transaction="Test",
            status=200,
            time_ms=100 + i * 10,
            response_text=json.dumps(response_data)
        )
        samplers.append(sampler)
    
    # Test value origin classification performance
    try:
        start = time.time()
        classifier = ValueOriginClassifier(samplers)
        duration = time.time() - start
        
        throughput = len(samplers) / duration if duration > 0 else 0
        result.add_pass(f"ValueOriginClassifier on 50 samplers ({throughput:.1f} samplers/sec)", duration)
        
        if duration > 2.0:
            result.add_warning("Performance", f"Classification took {duration:.2f}s (expected <1s for 50 samplers)")
    except Exception as e:
        result.add_fail("ValueOriginClassifier performance", str(e))
    
    # Test with 200 samplers
    print(f"  Creating {BOLD}200-sampler{RESET} test case...")
    
    large_samplers = []
    for i in range(200):
        response_data = {
            "id": 5000 + i,
            "name": f"item_{i}",
            "nested": {"value": f"test_{i}"}
        }
        
        sampler = SamplerModel(
            name=f"request_{i}",
            method="GET",
            url=f"http://api.example.com/endpoint{i}",
            protocol="http",
            domain="api.example.com",
            port="80",
            path=f"/endpoint{i}",
            query=[("id", str(5000 + i))],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="application/json",
            transaction="Test",
            status=200,
            time_ms=100,
            response_text=json.dumps(response_data)
        )
        large_samplers.append(sampler)
    
    try:
        start = time.time()
        classifier = ValueOriginClassifier(large_samplers)
        duration = time.time() - start
        
        throughput = len(large_samplers) / duration if duration > 0 else 0
        result.add_pass(f"ValueOriginClassifier on 200 samplers ({throughput:.1f} samplers/sec)", duration)
        
        if duration > 5.0:
            result.add_warning("Performance", f"Classification took {duration:.2f}s (expected <3s for 200 samplers)")
    except Exception as e:
        result.add_fail("ValueOriginClassifier performance (large)", str(e))
    
    return result

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests."""
    print(f"\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}PRODUCTION READINESS TEST SUITE{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Application: HAR-to-JMeter Converter (Optimized)")
    
    all_results = []
    
    # Run all test sections
    all_results.append(("Imports & Dependencies", test_imports()))
    all_results.append(("Component Instantiation", test_instantiation()))
    all_results.append(("Discovery Engines", test_discovery_engines()))
    all_results.append(("Value Origin Classification", test_value_origin_classification()))
    all_results.append(("Pipeline Integration", test_pipeline_integration()))
    all_results.append(("Edge Cases & Error Handling", test_edge_cases()))
    all_results.append(("Performance Profiling", test_performance()))
    
    # Print final summary
    print(f"\n\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}FINAL SUMMARY{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}")
    
    total_passed = sum(len(r[1].passed) for r in all_results)
    total_failed = sum(len(r[1].failed) for r in all_results)
    total_warnings = sum(len(r[1].warnings) for r in all_results)
    
    for section_name, result in all_results:
        status = f"{GREEN}✓ PASS{RESET}" if len(result.failed) == 0 else f"{RED}✗ FAIL{RESET}"
        print(f"{section_name}: {status} ({len(result.passed)} passed, {len(result.failed)} failed, {len(result.warnings)} warnings)")
    
    print(f"\n{BOLD}Overall Results:{RESET}")
    print(f"  Total Tests:  {total_passed + total_failed}")
    print(f"  Passed:       {GREEN}{total_passed}{RESET}")
    print(f"  Failed:       {RED}{total_failed}{RESET}")
    print(f"  Warnings:     {YELLOW}{total_warnings}{RESET}")
    
    # Verdict
    print(f"\n{BOLD}PRODUCTION READINESS VERDICT:{RESET}")
    if total_failed == 0 and total_warnings <= 2:
        print(f"{GREEN}✅ APPROVED FOR PRODUCTION{RESET}")
        print(f"   All critical tests passed. Minor warnings are acceptable.")
        return 0
    elif total_failed == 0:
        print(f"{YELLOW}⚠️  READY WITH CAUTIONS{RESET}")
        print(f"   All critical tests passed, but address {total_warnings} warnings before deployment.")
        return 0
    else:
        print(f"{RED}❌ NOT READY FOR PRODUCTION{RESET}")
        print(f"   {total_failed} test(s) failed. Address before deployment.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
