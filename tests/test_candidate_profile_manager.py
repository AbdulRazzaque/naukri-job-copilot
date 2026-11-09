"""
Unit and Regression Tests for Centralized Country-Based Candidate Information Manager
======================================================================================
Implements all 9 Mandatory Regression Tests specified in Section 9 of the requirements:
- Test 1: Senior MERN Developer, Mumbai -> +91 7972694663, INDIA
- Test 2: Full Stack Developer, Pune -> +91 7972694663, INDIA
- Test 3: Senior Software Engineer, Doha -> +974 77557982, QATAR / INTERNATIONAL
- Test 4: Senior Full Stack Developer, Dubai -> +974 77557982, QATAR / INTERNATIONAL
- Test 5: Software Engineer, Abu Dhabi -> +974 77557982, QATAR / INTERNATIONAL
- Test 6: External form with separate country-code dropdown -> Separate country code and national number
- Test 7: External form with combined phone input -> Combined international phone number
- Test 8: Form requests current residential address -> Verified residential only (never preferred work location)
- Test 9: Form requests preferred work location -> Mumbai, Kurla, Maharashtra, India
Plus validation, privacy masking, anti-cross-contamination, and audit logging tests.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend is in python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from candidate_manager import (
    getCandidateProfileByJobLocation,
    get_candidate_profile_by_job_location,
    CandidateProfileManager,
    mask_phone_number
)
from question_answering import QuestionAnsweringEngine, QuestionCategory
from database import log_application_contact_audit, format_final_application_report


class TestCandidateProfileManager(unittest.TestCase):

    # -------------------------------------------------------------
    # Mandatory Test 1: Senior MERN Developer, Mumbai
    # -------------------------------------------------------------
    def test_01_mumbai_job_selects_india_profile_and_phone(self):
        job_loc = "Senior MERN Developer, Mumbai"
        profile = getCandidateProfileByJobLocation(job_loc)
        
        self.assertEqual(profile["profile_name"], "INDIA")
        self.assertEqual(profile["classification"], "INDIA")
        self.assertEqual(profile["country_code"], "+91")
        self.assertEqual(profile["mobile_number"], "7972694663")
        self.assertEqual(profile["full_phone_number"], "+91 7972694663")
        self.assertTrue(profile["is_india"])
        self.assertFalse(profile["is_international"])

    # -------------------------------------------------------------
    # Mandatory Test 2: Full Stack Developer, Pune
    # -------------------------------------------------------------
    def test_02_pune_job_selects_india_profile_and_phone(self):
        job_loc = "Full Stack Developer, Pune"
        profile = getCandidateProfileByJobLocation(job_loc)
        
        self.assertEqual(profile["profile_name"], "INDIA")
        self.assertEqual(profile["classification"], "INDIA")
        self.assertEqual(profile["country_code"], "+91")
        self.assertEqual(profile["mobile_number"], "7972694663")
        self.assertEqual(profile["full_phone_number"], "+91 7972694663")
        self.assertTrue(profile["is_india"])

    # -------------------------------------------------------------
    # Mandatory Test 3: Senior Software Engineer, Doha
    # -------------------------------------------------------------
    def test_03_doha_job_selects_qatar_profile_and_phone(self):
        job_loc = "Senior Software Engineer, Doha"
        profile = getCandidateProfileByJobLocation(job_loc)
        
        self.assertEqual(profile["profile_name"], "QATAR / INTERNATIONAL")
        self.assertEqual(profile["classification"], "INTERNATIONAL")
        self.assertEqual(profile["country_code"], "+974")
        self.assertEqual(profile["mobile_number"], "77557982")
        self.assertEqual(profile["full_phone_number"], "+974 77557982")
        self.assertFalse(profile["is_india"])
        self.assertTrue(profile["is_international"])

    # -------------------------------------------------------------
    # Mandatory Test 4: Senior Full Stack Developer, Dubai
    # -------------------------------------------------------------
    def test_04_dubai_job_selects_qatar_international_profile(self):
        job_loc = "Senior Full Stack Developer, Dubai"
        profile = getCandidateProfileByJobLocation(job_loc)
        
        self.assertEqual(profile["profile_name"], "QATAR / INTERNATIONAL")
        self.assertEqual(profile["classification"], "INTERNATIONAL")
        self.assertEqual(profile["country_code"], "+974")
        self.assertEqual(profile["mobile_number"], "77557982")
        self.assertEqual(profile["full_phone_number"], "+974 77557982")
        self.assertTrue(profile["is_international"])

    # -------------------------------------------------------------
    # Mandatory Test 5: Software Engineer, Abu Dhabi
    # -------------------------------------------------------------
    def test_05_abu_dhabi_job_selects_qatar_international_profile(self):
        job_loc = "Software Engineer, Abu Dhabi"
        profile = getCandidateProfileByJobLocation(job_loc)
        
        self.assertEqual(profile["profile_name"], "QATAR / INTERNATIONAL")
        self.assertEqual(profile["classification"], "INTERNATIONAL")
        self.assertEqual(profile["country_code"], "+974")
        self.assertEqual(profile["mobile_number"], "77557982")
        self.assertEqual(profile["full_phone_number"], "+974 77557982")
        self.assertTrue(profile["is_international"])

    # -------------------------------------------------------------
    # Mandatory Test 6: External form with separate country-code dropdown
    # -------------------------------------------------------------
    def test_06_external_form_separate_country_code_dropdown(self):
        # India Job
        india_prof = getCandidateProfileByJobLocation("Mumbai, India")
        cc_in, nat_in = CandidateProfileManager.format_phone_inputs(india_prof, has_separate_country_code=True)
        self.assertEqual(cc_in, "+91")
        self.assertEqual(nat_in, "7972694663")
        self.assertNotIn("+91", nat_in, "National number must not contain country code prefix")

        # Qatar / International Job
        intl_prof = getCandidateProfileByJobLocation("Doha, Qatar")
        cc_intl, nat_intl = CandidateProfileManager.format_phone_inputs(intl_prof, has_separate_country_code=True)
        self.assertEqual(cc_intl, "+974")
        self.assertEqual(nat_intl, "77557982")
        self.assertNotIn("+974", nat_intl, "National number must not contain country code prefix")

    # -------------------------------------------------------------
    # Mandatory Test 7: External form with combined phone input
    # -------------------------------------------------------------
    def test_07_external_form_combined_phone_input(self):
        # India Job
        india_prof = getCandidateProfileByJobLocation("Pune, India")
        cc_in, full_in = CandidateProfileManager.format_phone_inputs(india_prof, has_separate_country_code=False)
        self.assertEqual(cc_in, "")
        self.assertEqual(full_in, "+91 7972694663")

        # International Job
        intl_prof = getCandidateProfileByJobLocation("Dubai, UAE")
        cc_intl, full_intl = CandidateProfileManager.format_phone_inputs(intl_prof, has_separate_country_code=False)
        self.assertEqual(cc_intl, "")
        self.assertEqual(full_intl, "+974 77557982")

    # -------------------------------------------------------------
    # Mandatory Test 8: Form requests current residential address
    # -------------------------------------------------------------
    def test_08_form_requests_current_residential_address_uses_only_verified_residence(self):
        india_prof = getCandidateProfileByJobLocation("Mumbai, India")
        res_india = CandidateProfileManager.resolve_location_field("Current Residential Address", india_prof)
        self.assertEqual(res_india["status"], "RESOLVED")
        self.assertEqual(res_india["value"], "Kurla, Mumbai, Maharashtra, India")
        self.assertNotEqual(res_india["value"], india_prof["preferred_work_location"])

        # Also via QuestionAnsweringEngine:
        qa = QuestionAnsweringEngine()
        ans = qa.process_question("What is your current residential address?", location_hint="Mumbai, India")
        self.assertIn("Kurla, Mumbai, Maharashtra, India", ans.get("answer"))

        # For Qatar job, if asked for residential address:
        intl_prof = getCandidateProfileByJobLocation("Doha, Qatar")
        res_intl = CandidateProfileManager.resolve_location_field("Current Residential Address", intl_prof)
        # Truthful verified residence must be India, NEVER fabricated Doha address!
        self.assertEqual(res_intl["status"], "RESOLVED")
        self.assertIn("Mumbai", res_intl["value"])
        self.assertNotIn("Doha", res_intl["value"], "Must NEVER fabricate Doha as current residential address!")

    # -------------------------------------------------------------
    # Mandatory Test 9: Form requests preferred work location
    # -------------------------------------------------------------
    def test_09_form_requests_preferred_work_location(self):
        india_prof = getCandidateProfileByJobLocation("Mumbai, Maharashtra")
        res = CandidateProfileManager.resolve_location_field("Preferred Work Location", india_prof)
        self.assertEqual(res["status"], "RESOLVED")
        self.assertEqual(res["value"], "Mumbai, Kurla, Maharashtra, India")

        # Also via QuestionAnsweringEngine:
        qa = QuestionAnsweringEngine()
        ans = qa.process_question("What is your preferred work location?", location_hint="Mumbai, India")
        self.assertIn("Mumbai, Kurla, Maharashtra, India", ans.get("answer"))

    # -------------------------------------------------------------
    # Test 10: Phone Number Privacy Masking
    # -------------------------------------------------------------
    def test_10_phone_masking_in_dashboard_logs(self):
        # India full phone
        masked_in = mask_phone_number("+91 7972694663")
        self.assertEqual(masked_in, "+91 ******4663")

        # Qatar full phone
        masked_qa = mask_phone_number("+974 77557982")
        self.assertEqual(masked_qa, "+974 ****7982")

        # Raw numbers
        self.assertEqual(mask_phone_number("7972694663"), "******4663")
        self.assertEqual(mask_phone_number("77557982"), "****7982")

    # -------------------------------------------------------------
    # Test 11: Validation Blocks Duplicate Country Codes
    # -------------------------------------------------------------
    def test_11_pre_submission_validation_blocks_duplicate_country_code(self):
        # Accidental +91 inside national field
        val = CandidateProfileManager.validate_phone_mapping(
            country_code_val="+91",
            national_number_val="+91 7972694663",
            is_india=True
        )
        self.assertFalse(val["is_valid"])
        self.assertTrue(any("Duplicate country code" in err for err in val["errors"]))

        # Accidental +974 inside national field
        val_qa = CandidateProfileManager.validate_phone_mapping(
            country_code_val="+974",
            national_number_val="+974 77557982",
            is_india=False
        )
        self.assertFalse(val_qa["is_valid"])
        self.assertTrue(any("Duplicate country code" in err for err in val_qa["errors"]))

    # -------------------------------------------------------------
    # Test 12: Validation Blocks Cross-Contamination
    # -------------------------------------------------------------
    def test_12_pre_submission_validation_blocks_cross_contamination(self):
        # Entering Qatar number in India job
        val_err1 = CandidateProfileManager.validate_phone_mapping(
            country_code_val="+91",
            national_number_val="77557982",
            is_india=True
        )
        self.assertFalse(val_err1["is_valid"])
        self.assertTrue(any("Cross-contamination" in err for err in val_err1["errors"]))

        # Entering India number in Qatar job
        val_err2 = CandidateProfileManager.validate_phone_mapping(
            country_code_val="+974",
            national_number_val="7972694663",
            is_india=False
        )
        self.assertFalse(val_err2["is_valid"])
        self.assertTrue(any("Cross-contamination" in err for err in val_err2["errors"]))

    # -------------------------------------------------------------
    # Test 13: Mandatory Local Residential Info Halts with NEEDS_USER_ACTION
    # -------------------------------------------------------------
    def test_13_mandatory_unknown_foreign_residence_requests_user_action(self):
        intl_prof = getCandidateProfileByJobLocation("Dubai, UAE")
        # If external site requires mandatory local street address / building name in UAE:
        res = CandidateProfileManager.resolve_location_field("Street Address", intl_prof, is_mandatory=True)
        self.assertEqual(res["status"], "NEEDS_USER_ACTION")
        self.assertTrue(len(res["reason"]) > 0)

    # -------------------------------------------------------------
    # Test 14: Contact Audit Logging and Execution Report
    # -------------------------------------------------------------
    def test_14_audit_logging_and_report_formatting(self):
        with patch("database.log_event") as mock_log:
            log_application_contact_audit(
                job_id="12345",
                company_name="Penta Consulting",
                job_title="Senior Software Engineer",
                job_location="Doha, Qatar",
                detected_country="Qatar",
                candidate_profile="QATAR / INTERNATIONAL",
                country_code="+974",
                masked_phone="+974 ****7982",
                submission_status="APPLICATION_CONFIRMED"
            )
            mock_log.assert_called_once()
            log_arg = mock_log.call_args[0][0]
            self.assertIn("+974 ****7982", log_arg)
            self.assertNotIn("77557982", log_arg, "Plain unmasked phone must not be logged")

        report = format_final_application_report(
            company_name="Penta Consulting",
            job_title="Senior Software Engineer",
            job_location="Doha, Qatar",
            platform="LinkedIn",
            phone_number="+974 ****7982",
            country_code="+974",
            detected_country="Qatar",
            candidate_profile="QATAR / INTERNATIONAL"
        )
        self.assertIn("Penta Consulting", report)
        self.assertIn("+974 ****7982", report)
        self.assertIn("QATAR / INTERNATIONAL", report)

    # -------------------------------------------------------------
    # Test 15: Pune Location Personalization
    # -------------------------------------------------------------
    def test_15_pune_job_profile_details(self):
        pune_prof = getCandidateProfileByJobLocation("Senior Full Stack Developer, Pune")
        self.assertEqual(pune_prof["profile_name"], "INDIA")
        self.assertEqual(pune_prof["city"], "Pune")
        self.assertEqual(pune_prof["postal_code"], "411048")
        self.assertEqual(pune_prof["pincode"], "411048")
        self.assertIn("Talab Chowk area in Kondhwa, Pune", pune_prof["residential_address"])
        self.assertIn("Talab Chowk area in Kondhwa, Pune", pune_prof["current_location"])
        self.assertEqual(pune_prof["mobile_number"], "7972694663")
        self.assertEqual(pune_prof["country_code"], "+91")

    # -------------------------------------------------------------
    # Test 16: Mumbai Location Personalization
    # -------------------------------------------------------------
    def test_16_mumbai_job_profile_details(self):
        mumbai_prof = getCandidateProfileByJobLocation("Senior Full Stack Developer, Mumbai")
        self.assertEqual(mumbai_prof["profile_name"], "INDIA")
        self.assertEqual(mumbai_prof["city"], "Mumbai")
        self.assertEqual(mumbai_prof["postal_code"], "400070")
        self.assertEqual(mumbai_prof["pincode"], "400070")
        self.assertIn("Kurla, Mumbai, Maharashtra, India", mumbai_prof["residential_address"])
        self.assertIn("Kurla, Mumbai, India", mumbai_prof["current_location"])
        self.assertEqual(mumbai_prof["mobile_number"], "7972694663")
        self.assertEqual(mumbai_prof["country_code"], "+91")

    # -------------------------------------------------------------
    # Test 17: QA Engine Resolves Location by Pune vs Mumbai
    # -------------------------------------------------------------
    def test_17_qa_engine_resolves_location_by_city(self):
        qa = QuestionAnsweringEngine()
        
        # Pune
        pune_addr = qa.process_question("What is your current residential address?", location_hint="Pune")
        self.assertIn("Talab Chowk area in Kondhwa, Pune", pune_addr["answer"])
        
        pune_pin = qa.process_question("What is your pincode?", location_hint="Pune")
        self.assertEqual(pune_pin["answer"], "411048")
        
        pune_loc_lang = qa.process_question("Location of Residence and Language:", location_hint="Pune")
        self.assertIn("Talab Chowk area in Kondhwa, Pune", pune_loc_lang["answer"])
        
        # Mumbai
        mum_addr = qa.process_question("What is your current residential address?", location_hint="Mumbai")
        self.assertIn("Kurla, Mumbai", mum_addr["answer"])
        
        mum_pin = qa.process_question("What is your pincode?", location_hint="Mumbai")
        self.assertEqual(mum_pin["answer"], "400070")


if __name__ == "__main__":
    unittest.main()

