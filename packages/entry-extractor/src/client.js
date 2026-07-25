// DART 요청용 HTTP 클라이언트: 공통 헤더, 요청 간 지연, 지수 백오프 재시도
const axios = require('axios');

const BASE_URL = 'https://dart.fss.or.kr';

const DEFAULT_HEADERS = {
  'User-Agent': 'dart-wrapper/0.1',
  Accept: 'text/html,application/xhtml+xml',
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 네트워크 오류/타임아웃 시 지수 백오프로 자동 재시도하는 GET.
 * @param {string} url 요청 URL
 * @param {object} [options] axios 옵션
 * @param {object} [retry] 재시도 옵션 { maxRetry, timeout, delayMs }
 * @returns {Promise<import('axios').AxiosResponse>}
 */
async function safeGet(url, options = {}, retry = {}) {
  const { maxRetry = 5, timeout = 20000, delayMs = 1000 } = retry;

  const requestOptions = {
    timeout,
    headers: { ...DEFAULT_HEADERS, ...(options.headers || {}) },
    ...options,
  };

  let attempt = 0;
  while (true) {
    try {
      if (delayMs > 0) await sleep(delayMs);
      return await axios.get(url, requestOptions);
    } catch (err) {
      if (++attempt > maxRetry) throw err;
      const wait = Math.min(1000 * 2 ** attempt, 10000);
      await sleep(wait);
    }
  }
}

module.exports = {
  BASE_URL,
  DEFAULT_HEADERS,
  sleep,
  safeGet,
};
