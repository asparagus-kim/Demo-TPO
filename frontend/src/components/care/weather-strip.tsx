import { WEATHER_STRIP } from "@/lib/care-data"

/** 2-1 날씨 띠 — 가로 꽉 참.
 *
 *  기획의 최소 높이는 120px 이지만 그건 **최소값**이다. 넓은 화면에서 120px 로
 *  두면 1376px 폭 기준 11:1 이 되어, 3:1 인 원본(2000×667)이 잘려 띠처럼만
 *  보인다. 화면이 넓어질수록 높이를 키워 사진이 사진처럼 보이게 한다.
 *
 *  고정 문구다. 패널의 실제 날씨 값과 연결하지 않는다(기획 명시). */
export function WeatherStrip() {
  return (
    <section
      className="relative isolate flex min-h-[140px] items-center overflow-hidden rounded-xl min-[760px]:min-h-[200px] min-[1200px]:min-h-[240px]"
      aria-label="오늘 날씨 안내"
    >
      <img
        src={WEATHER_STRIP.image}
        alt=""
        aria-hidden="true"
        className="absolute inset-0 size-full object-cover"
      />
      {/* 왼쪽 62% 까지 어둡게, 85% 지점에서 투명 — 왼쪽 글자의 가독성을 만든다.
          사진이 더 보이도록 농도를 낮췄다(.72/.62 → .55/.42). 그만큼 글자는
          그림자로 받친다 — 어둡게 덮는 대신 글자만 또렷하게 하는 쪽이
          사진을 살린다. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(90deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.42) 62%, rgba(0,0,0,0) 85%)",
        }}
      />
      <div className="relative flex w-full flex-wrap items-center justify-between gap-2 px-5 py-4">
        <p
          className="text-[22px] leading-tight font-bold text-white"
          style={{
            textShadow: "0 1px 4px rgba(0,0,0,.9), 0 0 14px rgba(0,0,0,.6)",
          }}
        >
          {WEATHER_STRIP.headline}
        </p>
        {/* 그라데이션은 왼쪽만 덮으므로(기획 지정) 오른쪽 글자는 밝은 사진 위에
            놓인다. 그라데이션을 건드리는 대신 글자에 그림자를 줘 가독성만 올린다. */}
        <p
          className="text-sm font-medium text-white"
          style={{
            textShadow: "0 1px 3px rgba(0,0,0,.85), 0 0 10px rgba(0,0,0,.5)",
          }}
        >
          {WEATHER_STRIP.trailing}
        </p>
      </div>
    </section>
  )
}
