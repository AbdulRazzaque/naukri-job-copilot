import os
import sys

# Ensure backend in pythonpath
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from technology_matcher import evaluate_technology_alignment

def test_1_mern_developer():
    res = evaluate_technology_alignment("MERN Developer", "Acme Corp", "Looking for MERN Stack Developer with React, Node, MongoDB")
    assert res["should_apply"] is True, f"Test 1 Failed: Expected APPLY, got {res}"
    assert res["match_score"] >= 65, f"Test 1 Failed: Expected score >= 65, got {res['match_score']}"
    print(f"Test 1 [MERN Developer -> APPLY]: PASSED ✅ (Score: {res['match_score']}%, Type: {res['match_type']})")

def test_2_mern_python_fullstack():
    res = evaluate_technology_alignment("MERN + Python Full Stack", "Tech Innovators", "We need a Full Stack engineer skilled in MERN with Python backend services")
    assert res["should_apply"] is True, f"Test 2 Failed: Expected APPLY, got {res}"
    assert res["is_mixed_technology"] is True
    print(f"Test 2 [MERN + Python Full Stack -> APPLY]: PASSED ✅ (Score: {res['match_score']}%, Mixed: {res['is_mixed_technology']})")

def test_3_react_nodejs_python():
    res = evaluate_technology_alignment("React + Node.js + Python Developer", "Global Systems", "Build modern frontends in React.js and microservices in Node.js and Python")
    assert res["should_apply"] is True, f"Test 3 Failed: Expected APPLY, got {res}"
    assert res["is_mixed_technology"] is True
    print(f"Test 3 [React + Node.js + Python -> APPLY]: PASSED ✅ (Score: {res['match_score']}%, Tech: {res['additional_tech_noted']})")

def test_4_dedicated_python_developer():
    res = evaluate_technology_alignment("Dedicated Python Developer", "DataWorks", "Core Python, Django, Flask, Pandas, Data pipelines")
    assert res["should_apply"] is False, f"Test 4 Failed: Expected SKIP, got {res}"
    assert res["reason_code"] == "PRIMARY_SPECIALIZATION_MISMATCH", f"Test 4 Failed: Expected PRIMARY_SPECIALIZATION_MISMATCH, got {res['reason_code']}"
    print(f"Test 4 [Dedicated Python Developer -> SKIP]: PASSED ✅ (Reason: {res['reason_code']})")

def test_5_python_backend_specialist():
    res = evaluate_technology_alignment("Python Backend Specialist", "CloudData Inc", "Design high-throughput Python backend microservices and FastAPI endpoints")
    assert res["should_apply"] is False, f"Test 5 Failed: Expected SKIP, got {res}"
    assert res["reason_code"] == "PRIMARY_SPECIALIZATION_MISMATCH", f"Test 5 Failed: Expected PRIMARY_SPECIALIZATION_MISMATCH, got {res['reason_code']}"
    print(f"Test 5 [Python Backend Specialist -> SKIP]: PASSED ✅ (Reason: {res['reason_code']})")

def test_6_mern_dotnet_csharp():
    res = evaluate_technology_alignment("MERN + .NET / C# Developer", "Enterprise Solutions", "Full stack development using React, Node.js alongside existing .NET / C# microservices")
    assert res["should_apply"] is True, f"Test 6 Failed: Expected APPLY, got {res}"
    assert res["is_mixed_technology"] is True
    print(f"Test 6 [MERN + .NET / C# -> APPLY]: PASSED ✅ (Score: {res['match_score']}%, Tech: {res['additional_tech_noted']})")

def test_7_dedicated_dotnet_developer():
    res = evaluate_technology_alignment("Dedicated .NET Developer", "FinTech Corp", "C#, ASP.NET Core, Entity Framework, SQL Server, WPF")
    assert res["should_apply"] is False, f"Test 7 Failed: Expected SKIP, got {res}"
    assert res["reason_code"] == "PRIMARY_SPECIALIZATION_MISMATCH", f"Test 7 Failed: Expected PRIMARY_SPECIALIZATION_MISMATCH, got {res['reason_code']}"
    print(f"Test 7 [Dedicated .NET Developer -> SKIP]: PASSED ✅ (Reason: {res['reason_code']})")

def test_8_dedicated_java_developer():
    res = evaluate_technology_alignment("Dedicated Java Developer", "Legacy Banking", "Core Java, Spring Boot, Microservices, Hibernate, Kafka")
    assert res["should_apply"] is False, f"Test 8 Failed: Expected SKIP, got {res}"
    assert res["reason_code"] == "PRIMARY_SPECIALIZATION_MISMATCH", f"Test 8 Failed: Expected PRIMARY_SPECIALIZATION_MISMATCH, got {res['reason_code']}"
    print(f"Test 8 [Dedicated Java Developer -> SKIP]: PASSED ✅ (Reason: {res['reason_code']})")

def test_9_mern_with_java_secondary():
    res = evaluate_technology_alignment("MERN Developer", "Digital Solutions", "Primary responsibilities: React.js, Node.js, Express, MongoDB. Secondary/preferred: Basic understanding of Java services is a plus.")
    assert res["should_apply"] is True, f"Test 9 Failed: Expected APPLY, got {res}"
    assert res["match_score"] >= 65, f"Test 9 Failed: Expected score >= 65, got {res['match_score']}"
    print(f"Test 9 [MERN + Java as secondary technology -> APPLY]: PASSED ✅ (Score: {res['match_score']}%, Explanation: {res['detailed_explanation']})")

if __name__ == "__main__":
    print("=" * 70)
    print("MANDATORY REGRESSION TESTS: CANDIDATE TECHNOLOGY PROFILE (Section 7)")
    print("=" * 70)
    test_1_mern_developer()
    test_2_mern_python_fullstack()
    test_3_react_nodejs_python()
    test_4_dedicated_python_developer()
    test_5_python_backend_specialist()
    test_6_mern_dotnet_csharp()
    test_7_dedicated_dotnet_developer()
    test_8_dedicated_java_developer()
    test_9_mern_with_java_secondary()
    print("=" * 70)
    print("ALL 9 MANDATORY REGRESSION TESTS PASSED WITH 100% ACCURACY! ✅")
    print("=" * 70)

