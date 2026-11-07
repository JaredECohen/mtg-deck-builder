import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";
export const runtime = "nodejs";

/** Brand mark: an orange card on the site background, with a sky name-line. */
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0c1118",
        }}
      >
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 4,
            background: "#f97316",
            display: "flex",
            paddingTop: 4,
            paddingLeft: 3,
            paddingRight: 3,
          }}
        >
          <div style={{ width: "100%", height: 3, borderRadius: 2, background: "#38bdf8" }} />
        </div>
      </div>
    ),
    { ...size },
  );
}
