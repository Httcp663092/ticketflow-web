<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
const props = defineProps<{
  title: string;
  rows: { label: string; count: number }[];
  trend?: boolean;
}>();
const chart = ref<SVGSVGElement>();
const max = computed(() => Math.max(1, ...props.rows.map((r) => r.count)));
const shown = computed(() =>
  props.trend ? props.rows : props.rows.slice(0, 12),
);
const height = computed(() =>
  props.trend ? 300 : Math.max(220, shown.value.length * 36 + 50),
);
const points = computed(() =>
  shown.value
    .map(
      (r, i) =>
        `${60 + (i * 700) / Math.max(1, shown.value.length - 1)},${240 - (r.count / max.value) * 180}`,
    )
    .join(" "),
);
async function download() {
  if (!chart.value) return;
  const svg = chart.value.cloneNode(true) as SVGSVGElement;
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  svg.setAttribute("width", "840");
  svg.setAttribute("height", String(height.value));
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(svg)], {
      type: "image/svg+xml;charset=utf-8",
    }),
  );
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 1680;
    canvas.height = height.value * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png"),
    );
    if (!blob) throw new Error();
    const png = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = png;
    a.download = `TicketFlow-${props.title}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(png), 1000);
  } catch {
    ElMessage.error("图表导出失败，请重试。");
  } finally {
    URL.revokeObjectURL(url);
  }
}
</script>
<template>
  <section class="analysis-chart">
    <div class="analysis-chart-heading">
      <h3>{{ title }}</h3>
      <el-button size="small" @click="download" :disabled="!rows.length"
        >导出 PNG</el-button
      >
    </div>
    <p v-if="!rows.length" class="muted">此筛选范围内暂无工单。</p>
    <svg
      v-else
      ref="chart"
      :viewBox="`0 0 840 ${height}`"
      role="img"
      :aria-label="title"
      style="
        width: 100%;
        display: block;
        background: white;
        font-family:
          Arial, &quot;PingFang SC&quot;, &quot;Microsoft YaHei&quot;,
          sans-serif;
      "
    >
      <title>{{ title }}</title>
      <rect width="840" :height="height" fill="white" />
      <text x="24" y="25" fill="#253e35" font-size="20" font-weight="600">
        {{ title }}{{ !trend && rows.length > 12 ? "（前12项）" : "" }}
      </text>
      <template v-if="trend">
        <line x1="60" y1="240" x2="760" y2="240" stroke="#dce7e1" />
        <text x="24" y="66" fill="#62766d" font-size="18">{{ max }}</text>
        <text x="32" y="244" fill="#62766d" font-size="18">0</text>
        <polyline
          :points="points"
          fill="none"
          stroke="#268065"
          stroke-width="3"
        />
        <circle
          v-for="(r, i) in shown"
          :key="i"
          :cx="60 + (i * 700) / Math.max(1, shown.length - 1)"
          :cy="240 - (r.count / max) * 180"
          r="3"
          fill="#268065"
        >
          <title>{{ r.label }}：{{ r.count }}</title>
        </circle>
        <template v-for="(r, i) in shown" :key="r.label">
          <text
            v-if="
              i === 0 ||
              i === shown.length - 1 ||
              (i % Math.max(1, Math.ceil(shown.length / 5)) === 0 &&
                i < shown.length - 2)
            "
            :x="60 + (i * 700) / Math.max(1, shown.length - 1)"
            y="270"
            text-anchor="middle"
            fill="#62766d"
            font-size="15"
          >
            {{ r.label.slice(5) }}
          </text>
        </template>
      </template>
      <template v-else>
        <g
          v-for="(r, i) in shown"
          :key="r.label"
          :transform="`translate(0,${45 + i * 36})`"
        >
          <text x="24" y="18" fill="#41594e" font-size="18">
            {{ r.label.length > 10 ? r.label.slice(0, 9) + "…" : r.label }}
            <title>{{ r.label }}</title>
          </text>
          <rect x="235" y="2" width="510" height="22" rx="5" fill="#eef4f0" />
          <rect
            x="235"
            y="2"
            :width="(r.count / max) * 510"
            height="22"
            rx="5"
            fill="#41977d"
          />
          <text x="760" y="18" fill="#253e35" font-size="18">
            {{ r.count }}
          </text>
        </g>
      </template>
    </svg>
  </section>
</template>
