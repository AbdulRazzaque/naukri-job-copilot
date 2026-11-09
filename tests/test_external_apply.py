import os
import sys

# Ensure backend in pythonpath
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from external_apply_engine import ExternalApplyEngine, ExternalApplyStages, ExternalFailureReasons

def test_stage_definitions():
    expected_stages = [
        "EXTERNAL_APPLY_DETECTED",
        "EXTERNAL_NAVIGATION_STARTED",
        "EXTERNAL_PAGE_OPENED",
        "EXTERNAL_JOB_VERIFIED",
        "APPLICATION_FORM_DETECTED",
        "FORM_ANALYSIS_COMPLETED",
        "FORM_FILLING_STARTED",
        "RESUME_UPLOAD_STARTED",
        "RESUME_UPLOAD_COMPLETED",
        "FORM_VALIDATED",
        "APPLICATION_SUBMITTED",
        "APPLICATION_CONFIRMED"
    ]
    for st in expected_stages:
        assert hasattr(ExternalApplyStages, st), f"Missing stage {st}"
    print("Test 1 [Stages Definition]: PASSED ✅")

def test_failure_reasons():
    expected_reasons = [
        "EXTERNAL_LINK_NOT_FOUND",
        "EXTERNAL_NAVIGATION_FAILED",
        "EXTERNAL_JOB_MISMATCH",
        "EXTERNAL_PAGE_UNAVAILABLE",
        "APPLICATION_FORM_NOT_FOUND",
        "RESUME_UPLOAD_FAILED",
        "FORM_VALIDATION_FAILED",
        "MISSING_REQUIRED_INFORMATION",
        "CAPTCHA_REQUIRED",
        "LOGIN_REQUIRED",
        "APPLICATION_SUBMISSION_FAILED",
        "APPLICATION_BLOCKED"
    ]
    for r in expected_reasons:
        assert hasattr(ExternalFailureReasons, r), f"Missing failure reason {r}"
    print("Test 2 [Failure Reasons Definition]: PASSED ✅")

def test_chandorkar_job_compatibility():
    """Verify that Node.js Developer @ Chandorkar Technologies in Pune (from user screenshot) passes eligibility!"""
    from location_matcher import match_location
    from ai_service import evaluate_job_relevance

    # 1. Location match
    job_loc = "Pune"
    is_loc_valid, matched, _ = match_location(job_loc, ["Mumbai", "Pune", "Remote"])
    assert is_loc_valid is True, "Location Pune should match candidate preferred locations"
    assert "Pune" in matched

    # 2. Score check
    score, should_apply, reason = evaluate_job_relevance("Node.js Developer", "Chandorkar Technologies", "Location: Pune, Experience: 2 - 5 years")
    assert score >= 65, f"Match score should be >= 65% for Node.js Developer, got {score}%"
    print(f"Test 3 [User Screenshot Chandorkar Technologies Node.js Developer Pune]: PASSED ✅ (Score: {score}%, Loc: {matched})")

if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING EXTERNAL APPLY MODULE TESTS")
    print("=" * 60)
    test_stage_definitions()
    test_failure_reasons()
    test_chandorkar_job_compatibility()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)

