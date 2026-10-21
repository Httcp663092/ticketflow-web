<script setup lang="ts">
import { ref, reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
type Ticket = {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  category: string;
  version: number;
  team_id: number | null;
};
const token = ref(""),
  role = ref(""),
  rows = ref<Ticket[]>([]),
  selected = ref<Ticket>(),
  history = ref<
    {
      id: number;
      message: string;
      created_at: string | null;
      internal: boolean;
      kind: string;
    }[]
  >([]);
const teams = ref<{ id: number; name: string }[]>([]),
  users = ref<
    {
      id: number;
      username: string;
      role: string;
      team_id: number | null;
      active: boolean;
    }[]
  >([]);
const labels: Record<string, string> = {
  open: "待受理",
  in_progress: "处理中",
  resolved: "待确认",
  closed: "已关闭",
  cancelled: "已取消",
  low: "低",
  normal: "普通",
  high: "高",
  urgent: "紧急",
  erp: "ERP 问题",
  operations: "运维工单",
};
type Attachment = { id: number; filename: string; size: number };
const attachments = ref<Attachment[]>([]),
  internalNote = ref(false),
  busy = ref(false);
const teamName = ref(""),
  newUser = reactive({
    username: "",
    password: "",
    role: "requester",
    team_id: null as number | null,
  });
const login = reactive({ username: "", password: "" }),
  form = reactive({
    title: "",
    description: "",
    category: "erp",
    priority: "normal",
    team_id: null as number | null,
  }),
  query = ref(""),
  note = ref(""),
  assignee = ref(1);
async function api(path: string, method = "GET", body?: unknown) {
  const res = await fetch("/api" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token.value ? { Authorization: "Bearer " + token.value } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    if (res.status === 401) token.value = "";
    const data = await res.json().catch(() => ({}));
    throw new Error(
      res.status === 409
        ? "工单或数据已变化，请刷新详情后重试"
        : res.status === 422
          ? "请检查必填内容、原因和字段长度"
          : res.status === 403
            ? "当前账号没有此操作权限"
            : res.status === 413
              ? "附件不能超过 10 MiB，且每个工单最多20个"
              : res.status === 415
                ? "附件类型或内容不符合要求"
                : String(data.detail || "操作失败：" + res.status),
    );
  }
  return res.json();
}
async function guard(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(String(e));
  } finally {
    busy.value = false;
  }
}
async function load() {
  rows.value = await api("/tickets?q=" + encodeURIComponent(query.value));
}
async function signIn() {
  internalNote.value = false;
  const data = await api("/auth/login", "POST", login);
  token.value = data.access_token;
  role.value = data.role;
  login.password = "";
  await load();
  teams.value = await api("/teams");
  if (role.value !== "requester") users.value = await api("/users");
}
async function create() {
  await api("/tickets", "POST", form);
  form.title = "";
  form.description = "";
  await load();
  ElMessage.success("工单已创建");
}
async function open(row: Ticket) {
  const [ticket, events, files] = await Promise.all([
    api(`/tickets/${row.id}`),
    api(`/tickets/${row.id}/events`),
    api(`/tickets/${row.id}/attachments`),
  ]);
  selected.value = ticket;
  history.value = events;
  attachments.value = files;
}
async function transition(status: string) {
  let reason = "";
  if (
    status === "cancelled" ||
    (status === "in_progress" &&
      ["closed", "resolved"].includes(selected.value!.status))
  ) {
    const result = await ElMessageBox.prompt(
      status === "cancelled" ? "请输入取消原因" : "请输入退回或重开原因",
      "填写原因",
      {
        inputType: "textarea",
        inputValidator: (value: string) =>
          (!!value?.trim() && value.trim().length <= 1000) ||
          "原因需填写，且不超过1000字",
        confirmButtonText: "确认",
        cancelButtonText: "返回",
      },
    );
    reason = result.value.trim();
  }
  selected.value = await api(`/tickets/${selected.value!.id}/status`, "PATCH", {
    status,
    version: selected.value!.version,
    reason,
  });
  await load();
  await open(selected.value!);
}
async function comment() {
  await api(`/tickets/${selected.value!.id}/comments`, "POST", {
    message: note.value,
    internal: role.value !== "requester" && internalNote.value,
  });
  note.value = "";
  await open(selected.value!);
}
async function assign() {
  selected.value = await api(
    `/tickets/${selected.value!.id}/assignee`,
    "PATCH",
    { assignee_id: assignee.value, version: selected.value!.version },
  );
  await load();
  await open(selected.value!);
}
async function addTeam() {
  await api("/teams", "POST", { name: teamName.value });
  teamName.value = "";
  teams.value = await api("/teams");
}
async function addUser() {
  await api("/users", "POST", newUser);
  newUser.password = "";
  newUser.username = "";
  users.value = await api("/users");
  ElMessage.success("账号已创建");
}
async function toggleUser(id: number, active: boolean) {
  await api("/users/" + id, "PATCH", { active });
  users.value = await api("/users");
}
function time(value: string | null) {
  return value
    ? new Date(
        value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value)
          ? value
          : value + "Z",
      ).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })
    : "历史时间未知";
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  if (!file || !selected.value) return;
  await guard(async () => {
    if (file.size > 10 * 1024 * 1024) throw new Error("附件不能超过 10 MiB");
    const response = await fetch(
      `/api/tickets/${selected.value!.id}/attachments?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token.value,
          "Content-Type": "application/octet-stream",
        },
        body: file,
      },
    );
    if (!response.ok)
      throw new Error(
        response.status === 413
          ? "附件不能超过 10 MiB，且每个工单最多20个"
          : response.status === 415
            ? "仅支持内容有效的 PNG、JPEG、PDF、UTF-8 TXT/CSV 文件"
            : "附件上传失败，请检查权限或刷新详情",
      );
    await open(selected.value!);
    await load();
    ElMessage.success("附件已上传");
  });
  input.value = "";
}
async function download(file: Attachment) {
  const response = await fetch(
    `/api/tickets/${selected.value!.id}/attachments/${file.id}`,
    { headers: { Authorization: "Bearer " + token.value } },
  );
  if (!response.ok) throw new Error("无法下载附件，请检查登录状态或权限");
  const url = URL.createObjectURL(await response.blob()),
    link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function eventText(message: string) {
  if (message === "Created") return "创建工单";
  const state = message.match(/^Status (\w+) -> (\w+)(?:; Reason: (.*))?$/s);
  if (state)
    return `${labels[state[1]] || state[1]} → ${labels[state[2]] || state[2]}${state[3] ? "；原因：" + state[3] : ""}`;
  if (message.startsWith("Attachment uploaded: "))
    return "上传附件：" + message.slice(21);
  if (message.startsWith("Assigned to "))
    return (
      "指派处理人：" +
      (users.value.find((u) => String(u.id) === message.slice(12))?.username ||
        message.slice(12))
    );
  return message;
}
</script>
<template>
  <main>
    <header>
      <div>
        <h1>TicketFlow</h1>
        <p>ERP 问题与运维工单</p>
      </div>
      <el-button
        :loading="busy"
        v-if="token"
        @click="
          token = '';
          selected = undefined;
          rows = [];
        "
        >退出登录</el-button
      >
    </header>
    <el-card v-if="!token" class="login"
      ><h2>登录工作台</h2>
      <el-form label-position="top" @submit.prevent="guard(signIn)"
        ><el-form-item label="用户名"
          ><el-input
            v-model="login.username"
            autocomplete="username" /></el-form-item
        ><el-form-item label="密码"
          ><el-input
            v-model="login.password"
            type="password"
            autocomplete="current-password"
            show-password /></el-form-item
        ><el-button :loading="busy" type="primary" native-type="submit"
          >登录</el-button
        ></el-form
      ></el-card
    >
    <template v-else
      ><el-card v-if="role === 'admin'"
        ><h2>账号与处理组管理</h2>
        <div class="options">
          <el-input v-model="teamName" placeholder="新处理组名称" /><el-button
            :loading="busy"
            @click="guard(addTeam)"
            >建立处理组</el-button
          >
        </div>
        <el-form label-position="top" @submit.prevent="guard(addUser)"
          ><div class="options">
            <el-input
              v-model="newUser.username"
              placeholder="新账号"
              required
            /><el-input
              v-model="newUser.password"
              placeholder="密码至少12位"
              type="password"
              autocomplete="new-password"
              required
            /><el-select v-model="newUser.role"
              ><el-option label="申请人" value="requester" /><el-option
                label="处理人"
                value="agent" /><el-option
                label="管理员"
                value="admin" /></el-select
            ><el-select
              v-model="newUser.team_id"
              placeholder="所属处理组"
              clearable
              ><el-option
                v-for="t in teams"
                :key="t.id"
                :label="t.name"
                :value="t.id" /></el-select
            ><el-button :loading="busy" native-type="submit"
              >创建账号</el-button
            >
          </div></el-form
        ><el-table :data="users"
          ><el-table-column prop="username" label="账号" /><el-table-column
            label="状态"
            ><template #default="{ row }">{{
              row.active ? "启用" : "停用"
            }}</template></el-table-column
          ><el-table-column label="操作"
            ><template #default="{ row }"
              ><el-button
                :loading="busy"
                v-if="row.role !== 'admin'"
                @click="guard(() => toggleUser(row.id, !row.active))"
                >{{ row.active ? "停用" : "启用" }}</el-button
              ></template
            ></el-table-column
          ></el-table
        ></el-card
      ><el-card
        ><h2>新建工单</h2>
        <el-form label-position="top" @submit.prevent="guard(create)"
          ><el-form-item label="标题"
            ><el-input
              v-model="form.title"
              maxlength="200"
              required /></el-form-item
          ><el-form-item label="问题描述"
            ><el-input
              v-model="form.description"
              type="textarea"
              :rows="3"
              required
          /></el-form-item>
          <div class="options">
            <el-select v-model="form.category" aria-label="分类"
              ><el-option label="ERP 问题" value="erp" /><el-option
                label="运维工单"
                value="operations" /></el-select
            ><el-select
              v-model="form.team_id"
              placeholder="选择处理组"
              clearable
              ><el-option
                v-for="t in teams"
                :key="t.id"
                :label="t.name"
                :value="t.id" /></el-select
            ><el-select v-model="form.priority" aria-label="优先级"
              ><el-option
                v-for="p in ['low', 'normal', 'high', 'urgent']"
                :key="p"
                :label="labels[p]"
                :value="p" /></el-select
            ><el-button :loading="busy" type="primary" native-type="submit"
              >提交工单</el-button
            >
          </div></el-form
        ></el-card
      >
      <el-card
        ><div class="options">
          <h2>工单列表</h2>
          <el-input
            v-model="query"
            placeholder="搜索标题或描述"
            @keyup.enter="guard(load)"
          /><el-button :loading="busy" @click="guard(load)">搜索</el-button>
        </div>
        <el-table
          :data="rows"
          @row-click="(row: Ticket) => guard(() => open(row))"
          ><el-table-column prop="id" label="编号" width="90" /><el-table-column
            prop="title"
            label="标题"
          /><el-table-column label="分类"
            ><template #default="{ row }">{{
              labels[row.category]
            }}</template></el-table-column
          ><el-table-column label="优先级"
            ><template #default="{ row }">{{
              labels[row.priority]
            }}</template></el-table-column
          ><el-table-column label="状态"
            ><template #default="{ row }">{{
              labels[row.status]
            }}</template></el-table-column
          ></el-table
        ></el-card
      >
      <el-drawer
        :model-value="!!selected"
        title="工单详情"
        size="min(600px, 100vw)"
        @close="selected = undefined"
        ><template v-if="selected"
          ><h2>{{ selected.title }}</h2>
          <p class="description">{{ selected.description }}</p>
          <el-tag>{{ labels[selected.status] }}</el-tag>
          <div class="options">
            <el-button
              :loading="busy"
              v-if="role !== 'requester' && selected.status === 'open'"
              @click="guard(() => transition('in_progress'))"
              >开始处理</el-button
            ><el-button
              :loading="busy"
              v-if="role !== 'requester' && selected.status === 'in_progress'"
              @click="guard(() => transition('resolved'))"
              >解决</el-button
            ><el-button
              :loading="busy"
              v-if="['closed', 'resolved'].includes(selected.status)"
              @click="guard(() => transition('in_progress'))"
              >{{
                selected.status === "closed" ? "重开工单" : "退回处理"
              }}</el-button
            ><el-button
              :loading="busy"
              v-if="
                role === 'admin' &&
                !['closed', 'cancelled'].includes(selected.status)
              "
              type="danger"
              plain
              @click="guard(() => transition('cancelled'))"
              >取消工单</el-button
            ><el-button
              :loading="busy"
              v-if="selected.status === 'resolved'"
              @click="guard(() => transition('closed'))"
              >确认关闭</el-button
            >
          </div>
          <div v-if="role === 'admin'" class="options">
            <el-select v-model="assignee" filterable placeholder="选择处理人"
              ><el-option
                v-for="u in users.filter(
                  (u) =>
                    u.active &&
                    (u.role === 'admin' ||
                      (u.role === 'agent' && u.team_id === selected?.team_id)),
                )"
                :key="u.id"
                :label="u.username"
                :value="u.id" /></el-select
            ><el-button :loading="busy" @click="guard(assign)"
              >指派处理人</el-button
            >
          </div>
          <el-button :loading="busy" @click="guard(() => open(selected!))"
            >刷新详情</el-button
          >
          <h3>附件</h3>
          <p class="hint">
            PNG、JPEG、PDF、UTF-8 TXT/CSV，单个不超过 10
            MiB，每个工单最多20个。当前工单内有权限的用户均可下载。
          </p>
          <label class="upload-label"
            >上传附件
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.pdf,.txt,.csv"
              :disabled="busy"
              @change="upload"
          /></label>
          <p v-if="!attachments.length" class="hint">暂无附件</p>
          <p v-for="file in attachments" :key="file.id">
            <el-button
              :loading="busy"
              link
              type="primary"
              @click="guard(() => download(file))"
              >{{ file.filename }}</el-button
            >
            <small>{{ Math.ceil(file.size / 1024) }} KB</small>
          </p>
          <h3>处理记录</h3>
          <p v-for="event in history" :key="event.id">
            <el-tag v-if="event.internal" type="warning" size="small"
              >内部备注</el-tag
            >
            {{
              event.kind === "system" ? eventText(event.message) : event.message
            }}
            <small>{{ time(event.created_at) }}</small>
          </p>
          <el-input
            v-model="note"
            type="textarea"
            placeholder="补充说明"
          /><el-checkbox v-if="role !== 'requester'" v-model="internalNote"
            >内部备注（申请人不可见）</el-checkbox
          ><el-button
            :loading="busy"
            :disabled="!note.trim()"
            @click="guard(comment)"
            >{{
              internalNote && role !== "requester" ? "保存内部备注" : "添加评论"
            }}</el-button
          ></template
        ></el-drawer
      >
    </template>
  </main>
</template>
<style>
body {
  margin: 0;
  background: #f3f6fa;
  color: #172b46;
  font-family: system-ui, sans-serif;
}
main {
  max-width: 1100px;
  margin: auto;
  padding: 32px 20px;
}
header,
.options {
  display: flex;
  align-items: center;
  gap: 16px;
  justify-content: space-between;
}
h1 {
  margin: 0;
  color: #2355b5;
}
header {
  margin-bottom: 28px;
}
.el-card {
  margin-bottom: 24px;
}
.login {
  max-width: 420px;
  margin: 60px auto;
}
.options .el-select {
  width: 220px;
}
.description {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
small,
.hint {
  color: #64748b;
}
.hint {
  font-size: 13px;
}
.upload-label {
  display: block;
  padding: 12px;
  background: #f3f6fa;
  border-radius: 6px;
}
.upload-label input {
  max-width: 100%;
  margin-top: 8px;
}
.options {
  margin: 16px 0;
}
h2 {
  font-size: 19px;
  white-space: nowrap;
}
@media (max-width: 600px) {
  .options {
    flex-wrap: wrap;
  }
}
</style>
