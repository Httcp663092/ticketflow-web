<script setup lang="ts">
import { computed, ref } from "vue";
import userManual from "../../docs/user-manual.md?raw";
import adminManual from "../../docs/admin-manual.md?raw";
const props = defineProps<{ admin: boolean }>();
const tab = ref("user");
const text = computed(() =>
  tab.value === "admin" && props.admin ? adminManual : userManual,
);
const sections = computed(() =>
  text.value.split(/^## /m).map((part, i) => {
    const [title, ...lines] = part.split("\n");
    return {
      title: i ? title : title.replace(/^# /, ""),
      body: lines.join("\n").trim(),
    };
  }),
);
function download() {
  const url = URL.createObjectURL(
    new Blob([text.value], { type: "text/markdown;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download =
    tab.value === "admin"
      ? "TicketFlow-管理端操作手册.md"
      : "TicketFlow-用户端操作手册.md";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>
<template>
  <section class="operation-guide">
    <div class="guide-toolbar">
      <el-radio-group v-model="tab"
        ><el-radio-button value="user">用户端手册</el-radio-button
        ><el-radio-button v-if="admin" value="admin"
          >管理端手册</el-radio-button
        ></el-radio-group
      ><el-button @click="download">下载手册</el-button>
    </div>
    <article v-for="(section, i) in sections" :key="i">
      <h2>{{ section.title }}</h2>
      <p>{{ section.body }}</p>
    </article>
  </section>
</template>
<style>
.operation-guide {
  background: white;
  border: 1px solid #dfe8e2;
  border-radius: 16px;
  padding: 28px;
  max-width: 1080px;
}
.guide-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 28px;
}
.operation-guide h2 {
  font-size: 19px;
  color: #264c3c;
  margin: 28px 0 14px;
}
.operation-guide p {
  white-space: pre-line;
  line-height: 1.95;
  color: #53685e;
  font-size: 14px;
}
.operation-guide article:first-of-type h2 {
  font-size: 25px;
}
@media (max-width: 560px) {
  .operation-guide {
    padding: 18px;
  }
}
</style>
