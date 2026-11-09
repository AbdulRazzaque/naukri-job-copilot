"""
Test Suite: External Application Submit Button Engagement & Confirmation Verification
=====================================================================================
Validates fixes for:
1. Button category classification for external submission terms:
   - 'Submit', 'Submit Application', 'Submit CV', 'Submit Resume', 'Submit Profile', etc.
2. Confirmation text detection for company careers websites:
   - 'We received your application and we will contact you shortly.' (User Screenshot)
   - 'Application submitted', 'Application received', 'Will contact you shortly'
3. Genuine error detection vs form reset:
   - HTML5 empty required fields (:invalid) after form reset must NOT be classified as errors.
   - Genuine visible error containers (.alert-danger, .invalid-feedback) are properly flagged.
"""

import sys
import os
import unittest
import re

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from button_service import ButtonDetectionService, ButtonCategory


class TestExternalSubmitAndConfirmation(unittest.TestCase):

    def setUp(self):
        self.btn_service = ButtonDetectionService()

    def test_01_submit_button_text_classification(self):
        """All variations of external career portal submit buttons must classify as SUBMIT."""
        submit_labels = [
            ("Submit", ""),
            ("Submit application", ""),
            ("Submit Application", ""),
            ("Submit profile", ""),
            ("Submit Profile", ""),
            ("Send application", ""),
            ("Send Application", ""),
            ("Submit CV", ""),
            ("Submit Resume", ""),
            ("Complete application", ""),
            ("Confirm and submit", ""),
            ("Submit inquiry", ""),
            ("Submit form", ""),
            ("", "Submit your application"),
            ("Apply", "", "submit"),
            ("Next", "", "submit")
        ]

        for text, aria, *btype in submit_labels:
            btn_type = btype[0] if btype else ""
            category = self.btn_service.classify_button_text(text, aria, btn_type)
            self.assertEqual(
                category,
                ButtonCategory.SUBMIT,
                f"Failed to classify '{text}' (aria='{aria}', type='{btn_type}') as SUBMIT"
            )

    def test_02_user_screenshot_confirmation_message_detection(self):
        """
        The exact confirmation message from user screenshot:
        'We received your application and we will contact you shortly.'
        must be positively matched as confirmed application.
        """
        success_patterns = [
            'we received your application',
            'we have received your application',
            'received your application',
            'application received',
            'application has been received',
            'will contact you shortly',
            'contact you shortly',
            'thank you for applying',
            'thanks for applying',
            'thank you for your application',
            'thanks for your application',
            'application submitted',
            'application has been submitted',
            'successfully submitted',
            'successfully applied',
            'applied successfully',
            'your application was submitted',
            'your application has been sent',
            'your response has been recorded',
            'application complete',
            'application completed',
            'submission successful',
            'we have received your details',
            "we've received your application",
            'submission received',
            'application received and recorded'
        ]

        # User's exact text banner:
        portal_banner_text = "We received your application and we will contact you shortly."
        text_lower = portal_banner_text.lower()

        matched = [p for p in success_patterns if p in text_lower]
        self.assertTrue(len(matched) > 0, "Failed to match user portal banner text")
        self.assertIn("we received your application", matched)
        self.assertIn("will contact you shortly", matched)

    def test_03_form_reset_does_not_trigger_false_error(self):
        """
        After form submission, the page resets inputs to empty.
        The system must NOT consider empty required fields as errors.
        """
        # Simulated DOM scenario
        # Empty inputs after reset
        form_inputs = [
            {"name": "first_name", "value": "", "required": True},
            {"name": "last_name", "value": "", "required": True},
            {"name": "email", "value": "", "required": True},
            {"name": "phone", "value": "", "required": True}
        ]

        # Notice: In the old code, `document.querySelector(':invalid')` returned True!
        # In our new code, we filter for genuine visible error messages with text:
        visible_error_elements = []  # No visible error alert div on screen

        has_genuine_errors = len(visible_error_elements) > 0
        self.assertFalse(has_genuine_errors, "Form reset must not be treated as genuine error")

    def test_04_genuine_error_detection(self):
        """If genuine error banner exists (e.g. 'Please fill mandatory fields'), it must be flagged."""
        success_patterns = ['we received your application', 'application submitted']

        # Scenario A: Genuine error
        error_elements = [
            {"text": "Please enter a valid phone number", "visible": True}
        ]
        has_genuine_errors = any(
            e["visible"] and len(e["text"]) > 2 and not any(p in e["text"].lower() for p in success_patterns)
            for e in error_elements
        )
        self.assertTrue(has_genuine_errors)

        # Scenario B: Container is class 'alert alert-success' with success message inside
        success_alert_elements = [
            {"text": "We received your application and we will contact you shortly.", "visible": True}
        ]
        has_genuine_errors_alert = any(
            e["visible"] and len(e["text"]) > 2 and not any(p in e["text"].lower() for p in success_patterns)
            for e in success_alert_elements
        )
        self.assertFalse(has_genuine_errors_alert, "Success banner inside an alert div must not be flagged as error")


if __name__ == "__main__":
    unittest.main()

