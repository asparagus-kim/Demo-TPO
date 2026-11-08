/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute origin of the FastAPI backend (e.g. https://yielda-api.onrender.com).
   * Empty in dev — requests then go to same-origin `/api` and Vite proxies them.
   */
  readonly VITE_API_BASE_URL?: string
  /**
   * Kakao Maps JavaScript 키 (developers.kakao.com — REST 키와 다른 키).
   * 도메인 화이트리스트로 보호되는 공개 키. 비우면 드로어의 미니 지도만 꺼진다.
   */
  readonly VITE_KAKAO_JS_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
