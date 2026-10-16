# Copyright (c) 2026, HeyKoala and contributors
# For license information, please see license.txt

"""The /kamra page serves the SPA shell only under its router basename.

Website Settings.home_page = "kamra" also renders this page at "/", where the
React router (basename /kamra) matches nothing and the screen stays blank, so
anything outside /kamra must redirect there."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from kamra.www import kamra as page


def _render(path):
	context = frappe._dict()
	with (
		patch.object(frappe, "request", SimpleNamespace(path=path)),
		patch.object(frappe.sessions, "get_csrf_token", return_value="tok"),
	):
		page.get_context(context)
	return context


class TestKamraPage(unittest.TestCase):
	def test_root_redirects_to_spa(self):
		frappe.local.flags.redirect_location = None
		with self.assertRaises(frappe.Redirect):
			_render("/")
		self.assertEqual(frappe.local.flags.redirect_location, "/kamra")

	def test_spa_routes_render_the_shell(self):
		for path in ("/kamra", "/kamra/setup", "/kamra/book/x"):
			context = _render(path)
			self.assertIn('window.csrf_token = "tok"', context.spa_html or "")
