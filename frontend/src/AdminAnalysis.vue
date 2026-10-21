<script setup lang="ts">
import { onMounted, ref, reactive, computed } from "vue";
import { ElMessage } from "element-plus";
import AnalysisChart from "./AnalysisChart.vue";
const props = defineProps<{
  request: (path: string) => Promise<Response>;
  teams: { id: number; name: string }[];
  users: { id: number; display_name: string; username: string; role: string }[];
}>();
type Group = { key: string | number; label: string; count: number };
type Report = {
  start: string;
  end: string;
  generated_at: string;
  summary: Record<string, number>;
  by_status: Group[];
  by_priority: Group[];
  by_category: Group[];
  by_team: Group[];
  by_assignee: Group[];
  trend: { date: string; count: number }[];
};
function day(d: Date) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(
    d,
  );
}
const today = new Date();
const ago = new Date(today);
ago.setDate(ago.getDate() - 29);
const range = ref<[string, string]>([day(ago), day(today)]);
const filters = reactive({
  status: "",
  category: "",
  priority: "",
  team_id: "",
  assignee_id: "",
});
const report = ref<Report>();
const loading = ref(false);
const exporting = ref(false);
const applied = ref("");
const dimensions = [
  ["by_status", "当前状态分布"],
  ["by_priority", "优先级分布"],
  ["by_category", "工单类型"],
  ["by_team", "处理组分布"],
  ["by_assignee", "处理人分布"],
] as const;
const metrics = [
  ["total", "工单总数"],
  ["active", "当前未关闭"],
  ["closed_rate", "当前关闭率"],
  ["unassigned_active", "未分派且未关闭"],
  ["urgent_active", "紧急且未关闭"],
];
const query = computed(() => {
  const q = new URLSearchParams();
  if (range.value?.length === 2) {
    q.set("start", range.value[0]);
    q.set("end", range.value[1]);
  }
  for (const [k, v] of Object.entries(filters)) if (v !== "") q.set(k, v);
  return q.toString();
});
async function load() {
  if (!range.value?.[0] || !range.value?.[1]) {
    ElMessage.warning("请选择完整日期范围。");
    return;
  }
  loading.value = true;
  const q = query.value;
  try {
    const response = await props.request("/admin/analytics?" + q);
    report.value = await response.json();
    applied.value = q;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "分析加载失败。");
  } finally {
    loading.value = false;
  }
}
function recent(days: number) {
  const d = new Date();
  const from = new Date(d);
  from.setDate(from.getDate() - days + 1);
  range.value = [day(from), day(d)];
}
async function exportCsv(kind: string) {
  exporting.value = true;
  try {
    const response = await props.request(
      "/admin/analytics/export?" + applied.value + "&kind=" + kind,
    );
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `TicketFlow-${kind === "summary" ? "汇总" : "明细"}-${report.value?.start}-${report.value?.end}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "导出失败。");
  } finally {
    exporting.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="analysis-workspace" v-loading="loading">
    <section class="analysis-filters">
      <div class="analysis-toolbar">
        <strong>选择分析范围</strong
        ><el-button-group
          ><el-button @click="recent(7)">近7天</el-button
          ><el-button @click="recent(30)">近30天</el-button
          ><el-button @click="recent(90)">近90天</el-button></el-button-group
        >
      </div>
      <el-form label-position="top" class="analysis-filter-grid">
        <el-form-item label="创建日期（北京时间）"
          ><el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            :clearable="false"
            style="width: 100%"
        /></el-form-item>
        <el-form-item label="当前状态"
          ><el-select v-model="filters.status" clearable placeholder="全部状态"
            ><el-option
              v-for="(label, key) in {
                open: '待受理',
                in_progress: '处理中',
                resolved: '待确认',
                closed: '已关闭',
                cancelled: '已取消',
              }"
              :key="key"
              :label="label"
              :value="key" /></el-select
        ></el-form-item>
        <el-form-item label="工单类型"
          ><el-select
            v-model="filters.category"
            clearable
            placeholder="全部类型"
            ><el-option label="ERP 问题" value="erp" /><el-option
              label="运维工单"
              value="operations" /></el-select
        ></el-form-item>
        <el-form-item label="优先级"
          ><el-select
            v-model="filters.priority"
            clearable
            placeholder="全部优先级"
            ><el-option
              v-for="(label, key) in {
                low: '低',
                normal: '普通',
                high: '高',
                urgent: '紧急',
              }"
              :key="key"
              :label="label"
              :value="key" /></el-select
        ></el-form-item>
        <el-form-item label="处理组"
          ><el-select
            v-model="filters.team_id"
            clearable
            filterable
            placeholder="全部处理组"
            ><el-option label="未分配" value="0" /><el-option
              v-for="t in teams"
              :key="t.id"
              :label="t.name"
              :value="String(t.id)" /></el-select
        ></el-form-item>
        <el-form-item label="处理人"
          ><el-select
            v-model="filters.assignee_id"
            clearable
            filterable
            placeholder="全部处理人"
            ><el-option label="未分派" value="0" /><el-option
              v-for="u in users.filter((u) => u.role !== 'requester')"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="String(u.id)" /></el-select
        ></el-form-item>
      </el-form>
      <div class="analysis-toolbar">
        <span class="muted">最长366天；筛选依据工单创建日期。</span
        ><el-button type="primary" @click="load" :loading="loading"
          >应用筛选</el-button
        >
      </div>
    </section>
    <template v-if="report">
      <div class="analysis-toolbar analysis-report-heading">
        <div>
          <h2>{{ report.start }} 至 {{ report.end }}</h2>
          <p class="muted">
            {{
              query !== applied
                ? "筛选条件已修改，请点击“应用筛选”。"
                : "图表与报表使用同一筛选范围。"
            }}
            当前状态快照，不代表当日结案量。
          </p>
        </div>
        <div class="analysis-actions">
          <el-button
            :loading="exporting"
            @click="exportCsv('summary')"
            :disabled="loading"
            >导出汇总 CSV</el-button
          ><el-button
            :loading="exporting"
            @click="exportCsv('details')"
            :disabled="loading"
            >导出明细 CSV</el-button
          >
        </div>
      </div>
      <div class="analysis-metrics">
        <article v-for="[key, label] in metrics" :key="key">
          <span>{{ label }}</span
          ><strong
            >{{ report.summary[key]
            }}{{ key === "closed_rate" ? "%" : "" }}</strong
          >
        </article>
      </div>
      <p class="analysis-definition">
        未关闭＝待受理＋处理中＋待确认。关闭率＝筛选范围内当前已关闭工单÷工单总数；已取消仍计入总数。明细最多导出10,000行，超出时请缩小范围。
      </p>
      <AnalysisChart
        :title="'每日新增工单 · ' + report.start + ' 至 ' + report.end"
        :rows="report.trend.map((r) => ({ label: r.date, count: r.count }))"
        trend
      />
      <div class="analysis-charts">
        <AnalysisChart
          v-for="[key, title] in dimensions"
          :key="key"
          :title="title + ' · ' + report.start + ' 至 ' + report.end"
          :rows="report[key]"
        />
      </div>
      <section class="analysis-chart">
        <h3>处理组数据明细</h3>
        <el-table :data="report.by_team" empty-text="暂无数据"
          ><el-table-column prop="label" label="处理组" /><el-table-column
            prop="count"
            label="工单数"
          /><el-table-column label="占比"
            ><template #default="scope"
              >{{
                report.summary.total
                  ? ((scope.row.count / report.summary.total) * 100).toFixed(1)
                  : "0.0"
              }}%</template
            ></el-table-column
          ></el-table
        >
      </section>
    </template>
  </div>
</template>
<style>
.analysis-workspace {
  display: grid;
  gap: 20px;
}
.analysis-filters,
.analysis-chart {
  background: white;
  border: 1px solid #dfe8e2;
  border-radius: 16px;
  padding: 22px;
  min-width: 0;
}
.analysis-toolbar,
.analysis-chart-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.analysis-filter-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 0 16px;
  margin-top: 20px;
}
.analysis-filter-grid .el-select {
  width: 100%;
}
.analysis-metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}
.analysis-metrics article {
  background: white;
  border: 1px solid #dfe8e2;
  border-radius: 14px;
  padding: 20px;
}
.analysis-metrics span {
  font-size: 13px;
  color: #62766d;
}
.analysis-metrics strong {
  display: block;
  margin-top: 12px;
  font-size: 30px;
  color: #1b4b3c;
}
.analysis-definition {
  font-size: 13px;
  color: #62766d;
  line-height: 1.8;
  margin: 0;
}
.analysis-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.analysis-chart h3 {
  margin: 0 0 14px;
}
.analysis-report-heading h2 {
  font-size: 20px;
  margin: 0 0 10px;
}
.analysis-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.analysis-actions .el-button + .el-button {
  margin: 0;
}
@media (max-width: 900px) {
  .analysis-filter-grid {
    grid-template-columns: 1fr 1fr;
  }
  .analysis-metrics {
    grid-template-columns: repeat(3, 1fr);
  }
  .analysis-charts {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 560px) {
  .analysis-filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .analysis-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .analysis-filters,
  .analysis-chart {
    padding: 15px;
  }
  .analysis-filter-grid .el-date-editor {
    min-width: 0;
  }
  .analysis-metrics strong {
    font-size: 25px;
  }
}
</style>
