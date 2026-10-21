<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import "./style.css";
type User = {
  id: number;
  username: string;
  display_name: string;
  role: string;
  team_id: number | null;
  active: boolean;
  registration_pending: boolean;
};
type Team = { id: number; name: string };
type Ticket = {
  id: number;
  title: string;
  description: string;
  category: string;
  priority: string;
  status: string;
  creator_id: number;
  creator_name?: string;
  assignee_id: number | null;
  assignee_name?: string;
  team_id: number | null;
  version: number;
  created_at: string;
  updated_at: string;
};
type History = {
  id: number;
  actor_id: number;
  actor_name?: string;
  message: string;
  internal: boolean;
  kind: string;
  created_at: string | null;
};
type Attachment = { id: number; filename: string; size: number };
const token = ref(""),
  me = ref<User>(),
  busy = ref(false),
  view = ref("dashboard"),
  authTab = ref("login");
const login = reactive({ username: "", password: "" }),
  registration = reactive({
    username: "",
    display_name: "",
    password: "",
    confirm: "",
  });
const rows = ref<Ticket[]>([]),
  users = ref<User[]>([]),
  teams = ref<Team[]>([]),
  total = ref(0),
  page = ref(1),
  pageSize = ref(10);
const filters = reactive({
  q: "",
  status: "",
  category: "",
  priority: "",
  mine: false,
  active_only: false,
});
const stats = ref<{
  total: number;
  by_status: Record<string, number>;
  urgent: number;
}>({ total: 0, by_status: {}, urgent: 0 });
const selected = ref<Ticket>(),
  events = ref<History[]>([]),
  attachments = ref<Attachment[]>([]),
  note = ref(""),
  internal = ref(false),
  assignee = ref<number>(),
  routingTeam = ref<number>();
const ticketDialog = ref(false),
  userDialog = ref(false),
  teamDialog = ref(false),
  editDialog = ref(false);
const teamName = ref(""),
  accountSearch = ref(""),
  edit = reactive({ id: 0, display_name: "", team_id: null as number | null });
const ticketForm = reactive({
  title: "",
  description: "",
  category: "erp",
  priority: "normal",
  team_id: null as number | null,
});
const userForm = reactive({
  username: "",
  display_name: "",
  password: "",
  role: "requester",
  team_id: null as number | null,
});
const passwordForm = reactive({
  current_password: "",
  new_password: "",
  confirm: "",
});
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
  requester: "申请人",
  agent: "处理人",
  admin: "管理员",
};
const headings: Record<string, string> = {
  dashboard: "工作台",
  tickets: "工单中心",
  users: "账号与处理组",
  settings: "个人设置",
};
const isStaff = computed(() => me.value?.role !== "requester");
const filteredUsers = computed(() =>
  users.value.filter((u) =>
    (u.username + " " + u.display_name)
      .toLowerCase()
      .includes(accountSearch.value.toLowerCase()),
  ),
);
const pending = computed(
  () => users.value.filter((u) => u.registration_pending).length,
);
const assignees = computed(() =>
  users.value.filter(
    (u) =>
      u.active &&
      (u.role === "admin" ||
        (u.role === "agent" && u.team_id === selected.value?.team_id)),
  ),
);
function logout() {
  ticketDialog.value = false;
  userDialog.value = false;
  teamDialog.value = false;
  editDialog.value = false;
  userForm.password = "";
  registration.password = "";
  registration.confirm = "";
  Object.assign(ticketForm, {
    title: "",
    description: "",
    category: "erp",
    priority: "normal",
    team_id: null,
  });
  teams.value = [];

  token.value = "";
  me.value = undefined;
  selected.value = undefined;
  rows.value = [];
  users.value = [];
  events.value = [];
  attachments.value = [];
  internal.value = false;
  passwordForm.current_password = "";
  passwordForm.new_password = "";
  passwordForm.confirm = "";
}
const errors: Record<string, string> = {
  "Invalid credentials": "账号或密码不正确；新注册账号需先通过管理员审核。",
  "Invalid or expired token": "登录已失效，请重新登录。",
  "Username already exists": "此账号已被使用，请更换。",
  "Team already exists": "处理组名称已存在。",
  "Unknown team": "处理组已变化，请刷新后重新选择。",
  "Current password incorrect": "当前密码不正确。",
  "New password must be different": "新密码不能与当前密码相同。",
  "A reason is required": "请填写操作原因。",
  "Invalid transition": "工单状态已变化，请刷新详情。",
  "Ticket changed; reload before retry":
    "工单已被其他人更新，请刷新详情后重试。",
  "At most 20 attachments per ticket": "每个工单最多上传20个附件。",
  "File exceeds 10 MiB": "单个附件不能超过10 MiB。",
  "Empty file": "不能上传空文件。",
};
async function request(
  path: string,
  method = "GET",
  body?: unknown,
  raw = false,
) {
  const res = await fetch(
    import.meta.env.BASE_URL.replace(/\/$/, "") + "/api" + path,
    {
      method,
      headers: {
        ...(token.value ? { Authorization: "Bearer " + token.value } : {}),
        ...(body !== undefined
          ? {
              "Content-Type": raw
                ? "application/octet-stream"
                : "application/json",
            }
          : {}),
      },
      body:
        body === undefined
          ? undefined
          : raw
            ? (body as Blob)
            : JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && token.value) logout();
    throw new Error(
      errors[data.detail] ||
        (res.status === 429
          ? "操作过于频繁，请15分钟后重试。"
          : res.status === 403
            ? "当前账号没有此操作权限。"
            : res.status === 404
              ? "内容不存在或你没有查看权限。"
              : res.status === 415
                ? "附件仅支持PNG、JPEG、PDF或UTF-8 TXT/CSV，且内容须符合类型。"
                : res.status === 422
                  ? "请检查必填项、账号格式和密码长度。"
                  : "操作未完成，请稍后重试。"),
    );
  }
  return res;
}
async function api(path: string, method = "GET", body?: unknown) {
  return (await request(path, method, body)).json();
}
async function guard(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
  } catch (e) {
    if (e !== "cancel" && e !== "close")
      ElMessage.error(e instanceof Error ? e.message : "操作已取消");
  } finally {
    busy.value = false;
  }
}
function time(value: string | null) {
  return value
    ? new Date(
        value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value)
          ? value
          : value + "Z",
      ).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })
    : "时间未记录";
}
function teamLabel(id: number | null) {
  return teams.value.find((t) => t.id === id)?.name || "未指定";
}
async function load() {
  const qs = new URLSearchParams({
    ...filters,
    mine: String(filters.mine),
    active_only: String(filters.active_only),
    offset: String((page.value - 1) * pageSize.value),
    limit: String(pageSize.value),
  });
  const [data, dashboard] = await Promise.all([
    api("/ticket-search?" + qs),
    api("/dashboard"),
  ]);
  rows.value = data.items;
  total.value = data.total;
  if (page.value > 1 && !data.items.length && data.total) {
    page.value = Math.ceil(data.total / pageSize.value);
    await load();
    return;
  }
  stats.value = dashboard;
}
async function loadPeople() {
  teams.value = await api("/teams");
  if (isStaff.value) users.value = await api("/users");
}
async function signIn() {
  const data = await api("/auth/login", "POST", login);
  token.value = data.access_token;
  me.value = await api("/auth/me");
  login.password = "";
  internal.value = false;
  view.value = "dashboard";
  await Promise.all([load(), loadPeople()]);
}
async function register() {
  if (registration.password !== registration.confirm)
    throw new Error("两次输入的密码不一致。");
  await api("/auth/register", "POST", {
    username: registration.username,
    display_name: registration.display_name,
    password: registration.password,
  });
  login.username = registration.username;
  registration.password = "";
  registration.confirm = "";
  authTab.value = "login";
  ElMessage.success({
    message: "注册申请已提交，请等待管理员审核后登录。",
    duration: 6000,
  });
}
async function navigate(next: string) {
  view.value = next;
  page.value = 1;
  if (next === "dashboard")
    Object.assign(filters, {
      q: "",
      status: "",
      category: "",
      priority: "",
      mine: false,
      active_only: false,
    });
  if (next === "dashboard" || next === "tickets") await load();
  if (next === "users") await loadPeople();
}
async function filter() {
  page.value = 1;
  await load();
}
async function resetFilters() {
  Object.assign(filters, {
    q: "",
    status: "",
    category: "",
    priority: "",
    mine: false,
    active_only: false,
  });
  await filter();
}
async function quickStatus(status: string) {
  Object.assign(filters, {
    q: "",
    category: "",
    priority: "",
    mine: false,
    active_only: false,
  });
  filters.status = status;
  view.value = "tickets";
  await filter();
}
async function createTicket() {
  await api("/tickets", "POST", ticketForm);
  ticketDialog.value = false;
  Object.assign(ticketForm, {
    title: "",
    description: "",
    category: "erp",
    priority: "normal",
    team_id: null,
  });
  ElMessage.success("工单已提交");
  view.value = "tickets";
  await resetFilters();
}
async function open(row: Ticket) {
  const [detail, history, files] = await Promise.all([
    api(`/tickets/${row.id}`),
    api(`/tickets/${row.id}/events`),
    api(`/tickets/${row.id}/attachments`),
  ]);
  selected.value = { ...row, ...detail };
  events.value = history;
  attachments.value = files;
  assignee.value = detail.assignee_id ?? undefined;
  routingTeam.value = detail.team_id ?? undefined;
}
async function transition(status: string) {
  let reason = "";
  if (
    status === "cancelled" ||
    (status === "in_progress" &&
      ["closed", "resolved"].includes(selected.value!.status))
  ) {
    const result = await ElMessageBox.prompt(
      status === "cancelled"
        ? "请说明取消这条工单的原因。"
        : "请描述仍存在的问题，便于处理人继续跟进。",
      status === "cancelled" ? "取消工单" : "退回 / 重开工单",
      {
        inputType: "textarea",
        inputValidator: (v: string) =>
          (!!v?.trim() && v.trim().length <= 1000) || "请填写1–1000字原因",
        confirmButtonText: "确认操作",
        cancelButtonText: "返回",
      },
    );
    reason = result.value.trim();
  }
  const detail = await api(`/tickets/${selected.value!.id}/status`, "PATCH", {
    status,
    version: selected.value!.version,
    reason,
  });
  await open({ ...selected.value!, ...detail });
  await load();
  ElMessage.success("工单状态已更新");
}
async function comment() {
  await api(`/tickets/${selected.value!.id}/comments`, "POST", {
    message: note.value,
    internal: isStaff.value && internal.value,
  });
  note.value = "";
  await open(selected.value!);
  await load();
}
async function assign() {
  await api(`/tickets/${selected.value!.id}/assignee`, "PATCH", {
    assignee_id: assignee.value,
    version: selected.value!.version,
  });
  await open(selected.value!);
  await load();
  ElMessage.success("已更新处理人");
}
async function routeTeam() {
  const result = await ElMessageBox.prompt(
    "请说明转派原因。原处理人会被清空，需要重新指派。",
    "转派处理组",
    {
      inputType: "textarea",
      inputValidator: (v: string) =>
        (!!v?.trim() && v.trim().length <= 1000) || "请填写1–1000字原因",
      confirmButtonText: "确认转派",
      cancelButtonText: "返回",
    },
  );
  await api(`/tickets/${selected.value!.id}/team`, "PATCH", {
    team_id: routingTeam.value,
    reason: result.value.trim(),
    version: selected.value!.version,
  });
  await open(selected.value!);
  await load();
  ElMessage.success("处理组已更新，请重新指派处理人");
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  if (!file || !selected.value) return;
  await guard(async () => {
    if (file.size > 10 * 1024 * 1024) throw new Error("单个附件不能超过10 MiB");
    await request(
      `/tickets/${selected.value!.id}/attachments?filename=${encodeURIComponent(file.name)}`,
      "POST",
      file,
      true,
    );
    await open(selected.value!);
    await load();
    ElMessage.success("附件已上传");
  });
  input.value = "";
}
async function download(file: Attachment) {
  const res = await request(
    `/tickets/${selected.value!.id}/attachments/${file.id}`,
  );
  const url = URL.createObjectURL(await res.blob()),
    link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function eventText(event: History) {
  const message = event.message;
  if (event.kind !== "system") return message;
  if (message === "Created") return "创建工单";
  const m = message.match(/^Status (\w+) -> (\w+)(?:; Reason: (.*))?$/s);
  if (m)
    return `${labels[m[1]]} → ${labels[m[2]]}${m[3] ? "；原因：" + m[3] : ""}`;
  if (message.startsWith("Attachment uploaded: "))
    return "上传附件：" + message.slice(21);
  if (message.startsWith("Routed to team: "))
    return (
      "转派处理组：" +
      message.slice(16).replace("; assignee cleared", "，原处理人已清空")
    );
  if (message.startsWith("Assigned to "))
    return (
      "指派给 " +
      (users.value.find((u) => String(u.id) === message.slice(12))
        ?.display_name || message.slice(12))
    );
  return message;
}
async function createUser() {
  await api("/users", "POST", userForm);
  userDialog.value = false;
  Object.assign(userForm, {
    username: "",
    display_name: "",
    password: "",
    role: "requester",
    team_id: null,
  });
  await loadPeople();
  ElMessage.success("账号已创建，可直接登录");
}
async function createTeam() {
  await api("/teams", "POST", { name: teamName.value });
  teamDialog.value = false;
  teamName.value = "";
  await loadPeople();
  ElMessage.success("处理组已创建");
}
async function toggleUser(user: User) {
  await ElMessageBox.confirm(
    user.registration_pending
      ? "通过审核后，此账号可登录并提交工单。"
      : user.active
        ? "停用后此账号将立即无法访问系统。"
        : "重新启用此账号？",
    user.registration_pending
      ? "审核注册申请"
      : user.active
        ? "停用账号"
        : "启用账号",
    { confirmButtonText: "确认", cancelButtonText: "返回", type: "warning" },
  );
  await api("/users/" + user.id, "PATCH", { active: !user.active });
  await loadPeople();
  ElMessage.success("账号状态已更新");
}
function editUser(user: User) {
  Object.assign(edit, {
    id: user.id,
    display_name: user.display_name,
    team_id: user.team_id,
  });
  editDialog.value = true;
}
async function saveUser() {
  await api("/users/" + edit.id, "PATCH", {
    display_name: edit.display_name,
    team_id: edit.team_id,
  });
  editDialog.value = false;
  await loadPeople();
  ElMessage.success("账号资料已保存");
}
async function changePassword() {
  if (passwordForm.new_password !== passwordForm.confirm)
    throw new Error("两次输入的新密码不一致。");
  await api("/auth/password", "POST", {
    current_password: passwordForm.current_password,
    new_password: passwordForm.new_password,
  });
  logout();
  ElMessage.success("密码已修改，请重新登录。");
}
</script>

<template>
  <div v-if="!token" class="auth-layout">
    <section class="auth-story">
      <a class="brand"><span class="brand-mark">T</span> TicketFlow</a>
      <div class="story-copy">
        <span class="eyebrow">ERP & OPERATIONS</span>
        <h1>让每一个问题，<br />都有清晰的下一步。</h1>
        <p>从问题提交到协作解决，<br />把进展、责任和记录放在同一个地方。</p>
        <div class="story-ticket">
          <div>
            <span class="status-dot"></span> 采购订单审核异常
            <span class="story-tag">处理中</span>
          </div>
          <div class="story-line"></div>
          <div class="story-steps">
            <span>✓ 提交问题</span><span>✓ 分派处理</span
            ><span>○ 确认解决</span>
          </div>
        </div>
      </div>
      <small>TicketFlow · ERP 运维协作工作台</small>
    </section>
    <section class="auth-panel">
      <div class="auth-card">
        <span class="eyebrow">欢迎使用 TICKETFLOW</span>
        <h2>{{ authTab === "login" ? "登录你的工作台" : "申请一个新账号" }}</h2>
        <p class="muted">
          {{
            authTab === "login"
              ? "查看工单进展，与团队一起解决问题。"
              : "注册后由管理员审核，为企业工单保留清晰的访问范围。"
          }}
        </p>
        <el-tabs v-model="authTab"
          ><el-tab-pane label="账号登录" name="login" /><el-tab-pane
            label="申请注册"
            name="register"
        /></el-tabs>
        <el-form
          v-if="authTab === 'login'"
          label-position="top"
          @submit.prevent="guard(signIn)"
          ><el-form-item label="账号"
            ><el-input
              v-model="login.username"
              autocomplete="username"
              placeholder="请输入账号"
              required
              maxlength="80" /></el-form-item
          ><el-form-item label="密码"
            ><el-input
              v-model="login.password"
              type="password"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              required /></el-form-item
          ><el-button
            type="primary"
            native-type="submit"
            class="full"
            :loading="busy"
            >登录工作台</el-button
          >
          <p class="form-hint">
            新注册账号需通过审核。忘记密码请联系管理员。
          </p></el-form
        >
        <el-form v-else label-position="top" @submit.prevent="guard(register)"
          ><el-form-item label="姓名 / 显示名称"
            ><el-input
              v-model="registration.display_name"
              required
              maxlength="80"
              placeholder="例如：张明" /></el-form-item
          ><el-form-item label="账号"
            ><el-input
              v-model="registration.username"
              required
              minlength="3"
              maxlength="40"
              placeholder="3–40位字母、数字、下划线、点或短横线"
              autocomplete="username"
              pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,39}" /></el-form-item
          ><el-form-item label="设置密码"
            ><el-input
              v-model="registration.password"
              required
              type="password"
              minlength="12"
              maxlength="128"
              placeholder="至少12位"
              show-password
              autocomplete="new-password" /></el-form-item
          ><el-form-item label="确认密码"
            ><el-input
              v-model="registration.confirm"
              required
              type="password"
              minlength="12"
              maxlength="128"
              placeholder="再次输入密码"
              autocomplete="new-password" /></el-form-item
          ><el-button
            type="primary"
            native-type="submit"
            class="full"
            :loading="busy"
            >提交注册申请</el-button
          >
          <p class="form-hint">
            默认申请人权限，不开放自行选择管理权限。
          </p></el-form
        >
      </div>
    </section>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand"><span class="brand-mark">T</span> TicketFlow</a
      ><span class="workspace-label">团队协作空间</span>
      <nav aria-label="主导航">
        <button
          v-for="item in [
            { key: 'dashboard', icon: '◫', label: '工作台' },
            { key: 'tickets', icon: '▤', label: '工单中心' },
            ...(me?.role === 'admin'
              ? [{ key: 'users', icon: '♙', label: '账号与处理组' }]
              : []),
            { key: 'settings', icon: '⚙', label: '个人设置' },
          ]"
          :key="item.key"
          :class="{ active: view === item.key }"
          @click="guard(() => navigate(item.key))"
        >
          <span class="nav-icon">{{ item.icon }}</span
          >{{ item.label
          }}<span v-if="item.key === 'users' && pending" class="nav-badge">{{
            pending
          }}</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <span class="avatar">{{ me?.display_name.slice(0, 1) }}</span>
        <div>
          <strong>{{ me?.display_name }}</strong
          ><small>{{ labels[me?.role || ""] }}</small>
        </div>
        <button
          class="logout"
          aria-label="退出登录"
          title="退出登录"
          @click="logout"
        >
          ↪
        </button>
      </div>
    </aside>
    <div class="app-body">
      <header class="topbar">
        <span
          >协作空间 <span class="breadcrumb">/ {{ headings[view] }}</span></span
        ><span class="topbar-user"
          >{{ me?.display_name }}
          <span class="role-pill">{{ labels[me?.role || ""] }}</span
          ><el-button link class="topbar-logout" @click="logout"
            >退出</el-button
          ></span
        >
      </header>
      <main class="content">
        <div class="page-heading">
          <div>
            <span class="eyebrow">{{
              view === "dashboard"
                ? "OVERVIEW"
                : view === "tickets"
                  ? "TICKET CENTER"
                  : view === "users"
                    ? "TEAM & ACCOUNTS"
                    : "YOUR PROFILE"
            }}</span>
            <h1>{{ headings[view] }}</h1>
            <p class="muted">
              {{
                view === "dashboard"
                  ? "从这里了解当前进展，找到需要跟进的事。"
                  : view === "tickets"
                    ? "让问题有记录，让处理有进展。"
                    : view === "users"
                      ? "审核注册申请，维护账号与团队分工。"
                      : "管理账号资料与登录密码。"
              }}
            </p>
          </div>
          <el-button
            v-if="['dashboard', 'tickets'].includes(view)"
            type="primary"
            size="large"
            @click="ticketDialog = true"
            >＋ 新建工单</el-button
          ><el-button
            v-if="view === 'users'"
            type="primary"
            @click="userDialog = true"
            >＋ 创建账号</el-button
          >
        </div>
        <template v-if="view === 'dashboard'"
          ><div class="stat-grid">
            <button class="stat-card" @click="guard(() => quickStatus(''))">
              <span>全部工单</span><strong>{{ stats.total }}</strong
              ><small>当前权限可见</small></button
            ><button
              class="stat-card"
              @click="guard(() => quickStatus('open'))"
            >
              <span>待受理</span><strong>{{ stats.by_status.open || 0 }}</strong
              ><small><i class="dot amber"></i> 等待分派与响应</small></button
            ><button
              class="stat-card"
              @click="guard(() => quickStatus('in_progress'))"
            >
              <span>处理中</span
              ><strong>{{ stats.by_status.in_progress || 0 }}</strong
              ><small><i class="dot teal"></i> 正在推进的问题</small></button
            ><button
              class="stat-card"
              @click="guard(() => quickStatus('resolved'))"
            >
              <span>待确认</span
              ><strong>{{ stats.by_status.resolved || 0 }}</strong
              ><small><i class="dot blue"></i> 等待验收解决结果</small>
            </button>
          </div>
          <div class="overview-row">
            <section class="panel flow-panel">
              <h3>处理状态分布</h3>
              <div
                v-for="state in [
                  'open',
                  'in_progress',
                  'resolved',
                  'closed',
                  'cancelled',
                ]"
                :key="state"
                class="bar-row"
              >
                <span>{{ labels[state] }}</span>
                <div>
                  <i
                    :class="state"
                    :style="{
                      width:
                        (stats.total
                          ? (100 * (stats.by_status[state] || 0)) / stats.total
                          : 0) + '%',
                    }"
                  ></i>
                </div>
                <b>{{ stats.by_status[state] || 0 }}</b>
              </div>
            </section>
            <section class="panel attention-panel">
              <span class="eyebrow">需要关注</span>
              <h3>
                紧急工单 <strong>{{ stats.urgent }}</strong>
              </h3>
              <p class="muted">优先跟进未完成的紧急问题。</p>
              <el-button
                @click="
                  guard(async () => {
                    Object.assign(filters, {
                      q: '',
                      category: '',
                      mine: false,
                      active_only: true,
                    });
                    filters.priority = 'urgent';
                    filters.status = '';
                    view = 'tickets';
                    await filter();
                  })
                "
                >查看紧急工单 →</el-button
              >
            </section>
          </div></template
        >
        <section
          v-if="['dashboard', 'tickets'].includes(view)"
          class="panel ticket-panel"
        >
          <div class="section-heading">
            <h3>
              {{ view === "dashboard" ? "最近更新" : "全部工单" }}
              <span class="count">{{ total }}</span>
            </h3>
            <el-button :loading="busy" @click="guard(load)">刷新</el-button>
          </div>
          <form class="filters" @submit.prevent="guard(filter)">
            <el-input
              v-model="filters.q"
              placeholder="搜索标题、描述或工单编号"
              clearable
              aria-label="搜索工单"
            /><el-select
              v-model="filters.status"
              placeholder="全部状态"
              clearable
              aria-label="工单状态"
              ><el-option
                v-for="state in [
                  'open',
                  'in_progress',
                  'resolved',
                  'closed',
                  'cancelled',
                ]"
                :key="state"
                :label="labels[state]"
                :value="state" /></el-select
            ><el-select
              v-model="filters.priority"
              placeholder="全部优先级"
              clearable
              aria-label="优先级筛选"
              ><el-option
                v-for="p in ['low', 'normal', 'high', 'urgent']"
                :key="p"
                :label="labels[p]"
                :value="p" /></el-select
            ><el-select
              v-model="filters.category"
              placeholder="全部分类"
              clearable
              aria-label="工单分类"
              ><el-option label="ERP 问题" value="erp" /><el-option
                label="运维工单"
                value="operations" /></el-select
            ><el-button
              type="primary"
              plain
              native-type="submit"
              :loading="busy"
              >查询</el-button
            ><el-button @click="guard(resetFilters)">重置</el-button>
          </form>
          <el-checkbox
            v-model="filters.mine"
            class="mine-filter"
            @change="guard(filter)"
            >只看我提交的工单</el-checkbox
          ><el-checkbox
            v-model="filters.active_only"
            class="mine-filter"
            @change="guard(filter)"
            >只看未完成</el-checkbox
          >
          <el-table
            :data="rows"
            class="ticket-table"
            @row-click="(row: Ticket) => guard(() => open(row))"
            ><el-table-column label="工单" min-width="290"
              ><template #default="{ row }"
                ><div class="ticket-title">{{ row.title }}</div>
                <small class="muted"
                  >TF-{{ String(row.id).padStart(5, "0") }} ·
                  {{ labels[row.category] }}</small
                ></template
              ></el-table-column
            ><el-table-column label="状态" width="112"
              ><template #default="{ row }"
                ><span :class="['status-pill', row.status]">{{
                  labels[row.status]
                }}</span></template
              ></el-table-column
            ><el-table-column label="优先级" width="95"
              ><template #default="{ row }"
                ><span :class="['priority', row.priority]"
                  ><i class="dot"></i>{{ labels[row.priority] }}</span
                ></template
              ></el-table-column
            ><el-table-column label="申请人 / 处理人" min-width="155"
              ><template #default="{ row }"
                ><span>{{ row.creator_name || "—" }}</span
                ><br /><small class="muted">{{
                  row.assignee_name || "待指派"
                }}</small></template
              ></el-table-column
            ><el-table-column label="更新时间" min-width="180"
              ><template #default="{ row }"
                ><small class="muted">{{
                  time(row.updated_at)
                }}</small></template
              ></el-table-column
            ><el-table-column label="操作" width="65"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  @click.stop="guard(() => open(row))"
                  >查看</el-button
                ></template
              ></el-table-column
            ><template #empty
              ><el-empty description="暂无符合条件的工单"
                ><el-button type="primary" @click="ticketDialog = true"
                  >新建第一条工单</el-button
                ></el-empty
              ></template
            ></el-table
          >
          <div class="mobile-list mobile-tickets">
            <button
              v-for="row in rows"
              :key="row.id"
              @click="guard(() => open(row))"
            >
              <div class="section-heading">
                <span class="eyebrow"
                  >TF-{{ String(row.id).padStart(5, "0") }}</span
                ><span :class="['status-pill', row.status]">{{
                  labels[row.status]
                }}</span>
              </div>
              <strong>{{ row.title }}</strong>
              <p class="muted">
                {{ labels[row.category] }} · {{ labels[row.priority] }}优先级 ·
                {{ row.assignee_name || "待指派" }}
              </p>
              <small class="muted">{{ time(row.updated_at) }}</small></button
            ><el-empty v-if="!rows.length" description="暂无符合条件的工单" />
          </div>
          <div class="table-footer">
            <span class="muted">共 {{ total }} 条工单</span
            ><el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :total="total"
              :page-sizes="[10, 20, 50]"
              layout="prev, pager, next, sizes"
              @current-change="guard(load)"
              @size-change="guard(filter)"
            />
          </div>
        </section>
        <template v-if="view === 'users'"
          ><div class="account-banner" v-if="pending">
            <span
              ><strong>{{ pending }} 位用户</strong>正在等待注册审核</span
            ><span class="muted">审核通过后才可登录系统</span>
          </div>
          <section class="panel">
            <div class="section-heading">
              <h3>团队账号</h3>
              <el-input
                v-model="accountSearch"
                class="account-search"
                placeholder="搜索姓名或账号"
                clearable
              />
            </div>
            <el-table class="account-table" :data="filteredUsers"
              ><el-table-column label="成员" min-width="170"
                ><template #default="{ row }"
                  ><strong>{{ row.display_name }}</strong
                  ><br /><small class="muted">{{
                    row.username
                  }}</small></template
                ></el-table-column
              ><el-table-column label="角色" width="110"
                ><template #default="{ row }">{{
                  labels[row.role]
                }}</template></el-table-column
              ><el-table-column label="处理组" min-width="140"
                ><template #default="{ row }">{{
                  teamLabel(row.team_id)
                }}</template></el-table-column
              ><el-table-column label="状态" width="110"
                ><template #default="{ row }"
                  ><el-tag
                    :type="
                      row.registration_pending
                        ? 'warning'
                        : row.active
                          ? 'success'
                          : 'info'
                    "
                    >{{
                      row.registration_pending
                        ? "待审核"
                        : row.active
                          ? "已启用"
                          : "已停用"
                    }}</el-tag
                  ></template
                ></el-table-column
              ><el-table-column label="操作" width="185"
                ><template #default="{ row }"
                  ><el-button link type="primary" @click="editUser(row)"
                    >编辑</el-button
                  ><el-button
                    v-if="row.role !== 'admin'"
                    link
                    :type="row.active ? 'danger' : 'primary'"
                    :loading="busy"
                    @click="guard(() => toggleUser(row))"
                    >{{
                      row.registration_pending
                        ? "通过审核"
                        : row.active
                          ? "停用"
                          : "启用"
                    }}</el-button
                  ></template
                ></el-table-column
              ></el-table
            >
            <div class="mobile-list mobile-accounts">
              <article v-for="user in filteredUsers" :key="user.id">
                <div class="section-heading">
                  <strong>{{ user.display_name }}</strong
                  ><el-tag
                    :type="
                      user.registration_pending
                        ? 'warning'
                        : user.active
                          ? 'success'
                          : 'info'
                    "
                    >{{
                      user.registration_pending
                        ? "待审核"
                        : user.active
                          ? "已启用"
                          : "已停用"
                    }}</el-tag
                  >
                </div>
                <p class="muted">
                  {{ user.username }} · {{ labels[user.role] }}<br />{{
                    teamLabel(user.team_id)
                  }}
                </p>
                <div class="mobile-actions">
                  <el-button @click="editUser(user)">编辑资料</el-button
                  ><el-button
                    v-if="user.role !== 'admin'"
                    :type="user.active ? 'danger' : 'primary'"
                    plain
                    @click="guard(() => toggleUser(user))"
                    >{{
                      user.registration_pending
                        ? "通过审核"
                        : user.active
                          ? "停用账号"
                          : "启用账号"
                    }}</el-button
                  >
                </div>
              </article>
              <el-empty
                v-if="!filteredUsers.length"
                description="没有匹配的账号"
              />
            </div>
          </section>
          <section class="panel team-panel">
            <div class="section-heading">
              <h3>处理组</h3>
              <el-button @click="teamDialog = true">＋ 建立处理组</el-button>
            </div>
            <div class="team-chips">
              <div v-for="team in teams" :key="team.id">
                <span class="team-icon">▤</span><strong>{{ team.name }}</strong
                ><small
                  >{{
                    users.filter((u) => u.team_id === team.id && u.active)
                      .length
                  }}
                  位启用成员</small
                >
              </div>
              <el-empty
                v-if="!teams.length"
                description="先建立处理组，再为成员指定归属"
              />
            </div></section
        ></template>
        <template v-if="view === 'settings'"
          ><section class="panel profile-panel">
            <span class="avatar large">{{ me?.display_name.slice(0, 1) }}</span>
            <div>
              <h3>{{ me?.display_name }}</h3>
              <p class="muted">
                {{ me?.username }} · {{ labels[me?.role || ""] }} ·
                {{ teamLabel(me?.team_id ?? null) }}
              </p>
            </div>
          </section>
          <section class="panel password-panel">
            <h3>修改登录密码</h3>
            <p class="muted">修改后，所有已有登录会话都需要重新登录。</p>
            <el-form
              label-position="top"
              @submit.prevent="guard(changePassword)"
              ><el-form-item label="当前密码"
                ><el-input
                  v-model="passwordForm.current_password"
                  type="password"
                  autocomplete="current-password"
                  required
                  show-password /></el-form-item
              ><el-form-item label="新密码"
                ><el-input
                  v-model="passwordForm.new_password"
                  type="password"
                  autocomplete="new-password"
                  minlength="12"
                  maxlength="128"
                  placeholder="至少12位"
                  required
                  show-password /></el-form-item
              ><el-form-item label="确认新密码"
                ><el-input
                  v-model="passwordForm.confirm"
                  type="password"
                  autocomplete="new-password"
                  minlength="12"
                  maxlength="128"
                  required /></el-form-item
              ><el-button type="primary" native-type="submit" :loading="busy"
                >保存新密码</el-button
              ></el-form
            >
          </section></template
        >
      </main>
      <footer class="app-footer">TicketFlow · 让协作有迹可循</footer>
    </div>
  </div>

  <el-dialog
    v-model="ticketDialog"
    title="新建工单"
    width="min(620px, 94vw)"
    :close-on-click-modal="false"
    ><el-form label-position="top" @submit.prevent="guard(createTicket)"
      ><el-form-item label="问题标题"
        ><el-input
          v-model="ticketForm.title"
          placeholder="用一句话说明遇到的问题"
          maxlength="200"
          show-word-limit
          required /></el-form-item
      ><el-form-item label="问题描述"
        ><el-input
          v-model="ticketForm.description"
          type="textarea"
          :rows="5"
          placeholder="请说明发生时间、操作步骤、错误提示及影响范围。提交后可在详情中添加附件。"
          maxlength="20000"
          required
      /></el-form-item>
      <div class="form-grid">
        <el-form-item label="工单分类"
          ><el-select v-model="ticketForm.category"
            ><el-option label="ERP 问题" value="erp" /><el-option
              label="运维工单"
              value="operations" /></el-select></el-form-item
        ><el-form-item label="优先级"
          ><el-select v-model="ticketForm.priority"
            ><el-option
              v-for="p in ['low', 'normal', 'high', 'urgent']"
              :key="p"
              :label="labels[p]"
              :value="p" /></el-select
        ></el-form-item>
      </div>
      <el-form-item label="处理组"
        ><el-select
          v-model="ticketForm.team_id"
          clearable
          placeholder="不知道归属时可留空，由管理员分派"
          ><el-option
            v-for="t in teams"
            :key="t.id"
            :label="t.name"
            :value="t.id" /></el-select
      ></el-form-item>
      <div class="dialog-actions">
        <el-button @click="ticketDialog = false">返回</el-button
        ><el-button type="primary" native-type="submit" :loading="busy"
          >提交工单</el-button
        >
      </div></el-form
    ></el-dialog
  >
  <el-drawer
    :model-value="!!selected"
    title="工单详情"
    size="min(720px, 100vw)"
    @close="
      selected = undefined;
      note = '';
      internal = false;
    "
    ><template v-if="selected"
      ><div class="detail-heading">
        <span class="eyebrow"
          >TF-{{ String(selected.id).padStart(5, "0") }}</span
        ><span :class="['status-pill', selected.status]">{{
          labels[selected.status]
        }}</span>
        <h2>{{ selected.title }}</h2>
        <div class="detail-meta">
          <span>{{ labels[selected.category] }}</span
          ><span>{{ labels[selected.priority] }}优先级</span
          ><span>{{ teamLabel(selected.team_id) }}</span>
        </div>
      </div>
      <div class="detail-actions">
        <el-button
          v-if="isStaff && selected.status === 'open'"
          type="primary"
          @click="guard(() => transition('in_progress'))"
          :loading="busy"
          >开始处理</el-button
        ><el-button
          v-if="isStaff && selected.status === 'in_progress'"
          type="primary"
          @click="guard(() => transition('resolved'))"
          :loading="busy"
          >标记解决</el-button
        ><el-button
          v-if="selected.status === 'resolved'"
          type="primary"
          @click="guard(() => transition('closed'))"
          :loading="busy"
          >确认关闭</el-button
        ><el-button
          v-if="['closed', 'resolved'].includes(selected.status)"
          @click="guard(() => transition('in_progress'))"
          :loading="busy"
          >{{
            selected.status === "closed" ? "重开工单" : "退回处理"
          }}</el-button
        ><el-button
          v-if="
            me?.role === 'admin' &&
            !['closed', 'cancelled'].includes(selected.status)
          "
          type="danger"
          plain
          @click="guard(() => transition('cancelled'))"
          :loading="busy"
          >取消工单</el-button
        ><el-button @click="guard(() => open(selected!))" :loading="busy"
          >刷新</el-button
        >
      </div>
      <section class="detail-section">
        <h3>问题描述</h3>
        <p class="description">{{ selected.description }}</p>
      </section>
      <section v-if="me?.role === 'admin'" class="detail-section">
        <h3>处理组与处理人</h3>
        <div class="inline-form routing-form">
          <el-select v-model="routingTeam" placeholder="选择处理组"
            ><el-option
              v-for="team in teams"
              :key="team.id"
              :value="team.id"
              :label="team.name" /></el-select
          ><el-button
            :disabled="!routingTeam || routingTeam === selected.team_id"
            :loading="busy"
            @click="guard(routeTeam)"
            >转派处理组</el-button
          >
        </div>
        <div class="inline-form">
          <el-select v-model="assignee" filterable placeholder="选择处理人"
            ><el-option
              v-for="u in assignees"
              :key="u.id"
              :label="u.display_name"
              :value="u.id" /></el-select
          ><el-button
            :disabled="!assignee"
            :loading="busy"
            @click="guard(assign)"
            >保存指派</el-button
          >
        </div>
      </section>
      <section class="detail-section">
        <div class="section-heading">
          <h3>
            附件 <span class="count">{{ attachments.length }}</span>
          </h3>
          <label class="upload-button"
            >＋ 上传附件<input
              type="file"
              accept=".png,.jpg,.jpeg,.pdf,.txt,.csv"
              :disabled="busy"
              @change="upload"
          /></label>
        </div>
        <p class="form-hint">
          PNG / JPEG / PDF / UTF-8 TXT、CSV · 单个10 MiB内 · 最多20个
        </p>
        <p v-if="!attachments.length" class="muted">暂无附件</p>
        <div class="attachment-row" v-for="file in attachments" :key="file.id">
          <span class="file-icon">▤</span>
          <div>
            <strong>{{ file.filename }}</strong
            ><small>{{ Math.ceil(file.size / 1024) }} KB</small>
          </div>
          <el-button link type="primary" @click="guard(() => download(file))"
            >下载</el-button
          >
        </div>
      </section>
      <section class="detail-section">
        <h3>处理记录</h3>
        <div class="timeline">
          <article
            v-for="event in events"
            :key="event.id"
            :class="{ internal: event.internal }"
          >
            <div class="timeline-meta">
              <strong>{{
                event.actor_name ||
                users.find((u) => u.id === event.actor_id)?.display_name ||
                "工单成员"
              }}</strong
              ><el-tag v-if="event.internal" type="warning" size="small"
                >内部备注</el-tag
              ><time>{{ time(event.created_at) }}</time>
            </div>
            <p>{{ eventText(event) }}</p>
          </article>
        </div>
      </section>
      <section class="comment-box">
        <el-input
          v-model="note"
          type="textarea"
          :rows="3"
          maxlength="10000"
          placeholder="补充信息或记录处理进展…"
        />
        <div class="section-heading">
          <el-checkbox v-if="isStaff" v-model="internal"
            >内部备注（申请人不可见）</el-checkbox
          ><span v-else class="muted">有权限的工单成员可查看</span
          ><el-button
            type="primary"
            :disabled="!note.trim()"
            :loading="busy"
            @click="guard(comment)"
            >{{ internal && isStaff ? "保存内部备注" : "发送评论" }}</el-button
          >
        </div>
      </section></template
    ></el-drawer
  >
  <el-dialog
    v-model="userDialog"
    title="创建团队账号"
    width="min(520px,94vw)"
    :close-on-click-modal="false"
    ><p class="muted">由管理员创建的账号无需审核，可直接登录。</p>
    <el-form label-position="top" @submit.prevent="guard(createUser)"
      ><div class="form-grid">
        <el-form-item label="显示名称"
          ><el-input
            v-model="userForm.display_name"
            required
            maxlength="80"
            placeholder="成员姓名" /></el-form-item
        ><el-form-item label="登录账号"
          ><el-input
            v-model="userForm.username"
            required
            minlength="3"
            maxlength="40"
            pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,39}"
            placeholder="英文或数字开头"
        /></el-form-item>
      </div>
      <el-form-item label="初始密码"
        ><el-input
          v-model="userForm.password"
          type="password"
          required
          minlength="12"
          maxlength="128"
          show-password
          autocomplete="new-password"
          placeholder="至少12位" /></el-form-item
      ><el-form-item label="账号角色"
        ><el-select v-model="userForm.role"
          ><el-option
            label="申请人：提交并追踪自己的工单"
            value="requester" /><el-option
            label="处理人：处理所属组工单"
            value="agent" /><el-option
            label="管理员：维护全局账号和工单"
            value="admin" /></el-select></el-form-item
      ><el-form-item label="所属处理组"
        ><el-select
          v-model="userForm.team_id"
          clearable
          placeholder="选择处理组"
          ><el-option
            v-for="t in teams"
            :key="t.id"
            :label="t.name"
            :value="t.id" /></el-select
      ></el-form-item>
      <div class="dialog-actions">
        <el-button @click="userDialog = false">返回</el-button
        ><el-button type="primary" native-type="submit" :loading="busy"
          >创建账号</el-button
        >
      </div></el-form
    ></el-dialog
  >
  <el-dialog v-model="teamDialog" title="建立处理组" width="min(460px,94vw)"
    ><el-form label-position="top" @submit.prevent="guard(createTeam)"
      ><el-form-item label="处理组名称"
        ><el-input
          v-model="teamName"
          maxlength="100"
          required
          placeholder="例如：ERP 财务支持组"
      /></el-form-item>
      <p class="muted">成员归组后，可查看与处理该组工单。</p>
      <div class="dialog-actions">
        <el-button type="primary" native-type="submit" :loading="busy"
          >建立处理组</el-button
        >
      </div></el-form
    ></el-dialog
  >
  <el-dialog v-model="editDialog" title="编辑账号资料" width="min(460px,94vw)"
    ><el-form label-position="top" @submit.prevent="guard(saveUser)"
      ><el-form-item label="显示名称"
        ><el-input
          v-model="edit.display_name"
          required
          maxlength="80" /></el-form-item
      ><el-form-item label="所属处理组"
        ><el-select v-model="edit.team_id" clearable placeholder="未指定"
          ><el-option
            v-for="t in teams"
            :key="t.id"
            :label="t.name"
            :value="t.id" /></el-select
      ></el-form-item>
      <div class="dialog-actions">
        <el-button type="primary" native-type="submit" :loading="busy"
          >保存修改</el-button
        >
      </div></el-form
    ></el-dialog
  >
</template>
