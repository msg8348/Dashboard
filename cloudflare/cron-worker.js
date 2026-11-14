// 옆집얼마 정기 실행용 Cloudflare Worker (Cron Triggers)
// GitHub 예약 실행이 자주 누락돼, Cloudflare가 정해진 시각에 GitHub Actions 실행을 대신 요청한다.
// 설정: Worker → Settings → Variables and Secrets 에 GH_TOKEN (GitHub Fine-grained token, 이 저장소 Actions: Read and write) 를 Secret 으로 저장
// Cron Triggers (UTC 기준):  13 21-23,0-2 * * *   /   23 4 * * *   /   37 8 * * *
//   = KST 06:13~11:13 매시간, 13:23, 17:37  (확인 모드: 새 공개가 있을 때만 수집·배포)

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
  // 주소로 접속해도 아무것도 실행하지 않음 (누구나 실행시키지 못하게)
  async fetch() {
    return new Response("ok");
  },
};

function dispatch(env) {
  return fetch("https://api.github.com/repos/msg8348/Dashboard/actions/workflows/Dashboard.yml/dispatches", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "nextdoorprice-cron",
    },
    body: JSON.stringify({ ref: "main", inputs: { fetch: "true", probe: "true" } }),
  });
}
