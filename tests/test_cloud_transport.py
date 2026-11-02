"""Exercise real HTTP framing without contacting a paid image provider."""
import http.client
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.request import Request

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cloud


class MemorySocket:
    def __init__(self, response):
        self.response = response

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.response)


def http_response(body, headers=None):
    fields = {'Connection': 'close'}
    fields.update(headers or {})
    head = 'HTTP/1.1 200 OK\r\n' + ''.join(
        '%s: %s\r\n' % (name, value) for name, value in fields.items())
    response = http.client.HTTPResponse(MemorySocket(head.encode('ascii') + b'\r\n' + body))
    response.begin()
    return response


class ResponseFramingTests(unittest.TestCase):
    def fetch_response(self, response, limit=1024):
        # Keep these socket-free tests independent of the Windows certificate helper.
        with patch('cloud.sys.platform', 'linux'), patch('cloud.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            return cloud.fetch(Request('https://example.invalid/image'), 5, limit)

    def test_content_length_complete_at_size_limit(self):
        body = b'{"data":[]}'
        self.assertEqual(self.fetch_response(
            http_response(body, {'Content-Length': len(body)}), len(body)), body)

    def test_premature_eof_with_content_length_is_rejected(self):
        body = b'{"data":[{"b64_json":"private-payload'
        response = http_response(body, {'Content-Length': len(body) + 200})
        with self.assertRaises(cloud.IncompleteImageResponse) as caught:
            self.fetch_response(response)
        self.assertNotIn('private-payload', str(caught.exception))

    def test_complete_response_without_content_length(self):
        body = b'{"data":[]}'
        self.assertEqual(self.fetch_response(http_response(body)), body)

    def test_oversized_response_with_and_without_content_length(self):
        for headers in ({'Content-Length': 17}, {}):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                self.fetch_response(http_response(b'x' * 17, headers), 16)

    def test_complete_chunked_response(self):
        response = http_response(b'3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n',
                                 {'Transfer-Encoding': 'chunked'})
        self.assertEqual(self.fetch_response(response, 5), b'abcde')

    def test_truncated_chunk_and_missing_terminator_are_rejected(self):
        for body in (b'5\r\nabc', b'3\r\nabc\r\n'):
            with self.subTest(body=body), self.assertRaises(cloud.IncompleteImageResponse):
                self.fetch_response(http_response(body, {'Transfer-Encoding': 'chunked'}))


class GenerationResponseTests(unittest.TestCase):
    def setUp(self):
        stream = io.BytesIO()
        Image.new('RGB', (32, 32), 'white').save(stream, format='PNG')
        self.image = stream.getvalue()
        self.cfg = dict(protocol='image_json', endpoint='https://example.invalid/generate',
                        model='test-model')
        self.credentials = patch.dict(os.environ, SO101_IMAGE_API_KEY='synthetic-test-key')
        self.credentials.start()
        self.addCleanup(self.credentials.stop)

    def test_invalid_json_and_encoding_have_safe_user_message(self):
        for body in (b'{"data":[{"b64_json":"private-payload', b'{"data":"\xff"}'):
            calls = []

            def transport(request, timeout, limit):
                calls.append(request)
                return body

            with self.subTest(body=body), self.assertRaisesRegex(ValueError, '不完整或格式异常') as caught:
                cloud.generate(self.image, self.cfg, transport=transport)
            self.assertNotIn('private-payload', str(caught.exception))
            self.assertEqual(len(calls), 1, 'Malformed JSON must not repeat a billed POST')

    def test_non_object_json_is_rejected_as_user_error(self):
        for body in (b'null', b'[]', b'"text"'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                cloud.generate(self.image, self.cfg, transport=lambda *args: body)

    def test_incomplete_generation_post_is_never_retried(self):
        calls = []

        def transport(request, timeout, limit):
            calls.append(request)
            raise cloud.IncompleteImageResponse('response interrupted')

        with self.assertRaises(cloud.IncompleteImageResponse):
            cloud.generate(self.image, self.cfg, transport=transport)
        self.assertEqual([request.get_method() for request in calls], ['POST'])

    def test_incomplete_image_get_retries_once_without_credentials(self):
        calls = []

        def transport(request, timeout, limit):
            calls.append(request)
            if request.get_method() == 'POST':
                return json.dumps({'data': [{'url': 'https://images.invalid/result.png'}]}).encode()
            if len(calls) == 2:
                raise cloud.IncompleteImageResponse('response interrupted')
            return self.image

        output, info = cloud.generate(self.image, self.cfg, transport=transport)
        self.assertTrue(output.startswith(b'\x89PNG'))
        self.assertEqual(info['actual_size'], [32, 32])
        self.assertEqual([request.get_method() for request in calls], ['POST', 'GET', 'GET'])
        for request in calls[1:]:
            self.assertFalse(request.has_header('Authorization'))

    def test_second_incomplete_image_get_fails_without_another_post(self):
        calls = []

        def transport(request, timeout, limit):
            calls.append(request)
            if request.get_method() == 'POST':
                return b'{"data":[{"url":"https://images.invalid/result.png"}]}'
            raise cloud.IncompleteImageResponse('response interrupted')

        with self.assertRaises(cloud.IncompleteImageResponse):
            cloud.generate(self.image, self.cfg, transport=transport)
        self.assertEqual([request.get_method() for request in calls], ['POST', 'GET', 'GET'])

    def test_other_image_download_failure_is_not_retried(self):
        calls = []

        def transport(request, timeout, limit):
            calls.append(request)
            if request.get_method() == 'POST':
                return b'{"data":[{"url":"https://images.invalid/result.png"}]}'
            raise ValueError('image exceeds size limit')

        with self.assertRaisesRegex(ValueError, 'size limit'):
            cloud.generate(self.image, self.cfg, transport=transport)
        self.assertEqual([request.get_method() for request in calls], ['POST', 'GET'])


if __name__ == '__main__':
    unittest.main()
