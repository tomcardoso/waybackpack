#!/usr/bin/env python
import unittest
from unittest.mock import MagicMock

import waybackpack


class Test(unittest.TestCase):
    def test_filters_passed_through(self):
        res = MagicMock()
        res.status_code = 200
        res.json.return_value = []
        s = MagicMock()
        s.get.return_value = res
        waybackpack.search("example.com", session=s)
        assert s.get.call_args[1]["params"]["filter"] is None
        filters = ["mimetype:application/pdf", "!statuscode:404"]
        waybackpack.search("example.com", session=s, filters=filters)
        assert s.get.call_args[1]["params"]["filter"] == filters


if __name__ == "__main__":
    unittest.main()
