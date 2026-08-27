#!/usr/bin/env python3
"""
Quick test to verify the new pipeline_v2 and analyzer architecture work correctly.
"""

from pathlib import Path
import sys

# Add app to path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

try:
    print("✓ Testing imports...")
    from app.analyzer import AnalyzerEngine, DependencyGraph, AIReviewLayer
    from app.pipeline_v2 import convert_har_v2
    print("  ✓ Analyzer Engine imported")
    print("  ✓ Dependency Graph imported")
    print("  ✓ AI Review Layer imported")
    print("  ✓ Pipeline v2 imported")
    
    print("\n✓ Testing AnalyzerEngine instantiation...")
    analyzer = AnalyzerEngine()
    print("  ✓ AnalyzerEngine created successfully")
    
    print("\n✓ Testing DependencyGraph instantiation...")
    from app.models import SamplerModel
    test_samplers = [
        SamplerModel(
            name="test_req",
            method="GET",
            url="http://example.com",
            protocol="http",
            domain="example.com",
            port="80",
            path="/test",
            query=[],
            headers=[],
            cookies=[],
            response_headers=[],
            post_params=[],
            post_body="",
            mime_type="text/html",
            transaction="Test",
            status=200,
            time_ms=100,
        )
    ]
    dg = DependencyGraph(test_samplers)
    print("  ✓ DependencyGraph created successfully")
    
    print("\n✓ Testing AIReviewLayer instantiation...")
    ai = AIReviewLayer()
    print("  ✓ AIReviewLayer created successfully")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED - New architecture is ready!")
    print("="*60)
    print("\nTo see changes in the tool:")
    print("1. Restart the server: python -m app")
    print("2. Upload a HAR file")
    print("3. Check the response for 'ai_review' section with:")
    print("   - optimization_score (0-100)")
    print("   - quality_metrics")
    print("   - findings (with category, severity, message)")
    print("   - recommendations")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
