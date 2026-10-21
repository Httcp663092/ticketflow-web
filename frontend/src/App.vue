<script setup lang="ts">
import {ref, reactive} from 'vue'
import {ElMessage} from 'element-plus'
type Ticket={id:number;title:string;description:string;status:string;priority:string;category:string}
const token=ref(''), role=ref(''), rows=ref<Ticket[]>([]), selected=ref<Ticket>(), history=ref<{id:number;message:string}[]>([])
const login=reactive({username:'',password:''}), form=reactive({title:'',description:'',category:'erp',priority:'normal'}), query=ref(''), note=ref(''), assignee=ref(1)
async function api(path:string,method='GET',body?:unknown){
 const res=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json',...(token.value?{Authorization:'Bearer '+token.value}:{})},body:body?JSON.stringify(body):undefined})
 if(!res.ok){if(res.status===401)token.value='';throw new Error('操作失败：'+res.status)}
 return res.json()
}
async function guard(action:()=>Promise<void>){try{await action()}catch(e){ElMessage.error(String(e))}}
async function load(){rows.value=await api('/tickets?q='+encodeURIComponent(query.value))}
async function signIn(){const data=await api('/auth/login','POST',login);token.value=data.access_token;role.value=data.role;login.password='';await load()}
async function create(){await api('/tickets','POST',form);form.title='';form.description='';await load();ElMessage.success('工单已创建')}
async function open(row:Ticket){selected.value=row;history.value=await api(`/tickets/${row.id}/events`)}
async function transition(status:string){selected.value=await api(`/tickets/${selected.value!.id}/status`,'PATCH',{status});await load();await open(selected.value!)}
async function comment(){await api(`/tickets/${selected.value!.id}/comments`,'POST',{message:note.value});note.value='';await open(selected.value!)}
async function assign(){selected.value=await api(`/tickets/${selected.value!.id}/assignee`,'PATCH',{assignee_id:assignee.value});await open(selected.value!)}
</script>
<template>
<main><header><div><h1>TicketFlow</h1><p>ERP 问题与运维工单</p></div><el-button v-if="token" @click="token='';selected=undefined;rows=[]">退出登录</el-button></header>
<el-card v-if="!token" class="login"><h2>登录工作台</h2><el-form label-position="top" @submit.prevent="guard(signIn)"><el-form-item label="用户名"><el-input v-model="login.username" autocomplete="username" /></el-form-item><el-form-item label="密码"><el-input v-model="login.password" type="password" autocomplete="current-password" show-password /></el-form-item><el-button type="primary" native-type="submit">登录</el-button></el-form></el-card>
<template v-else><el-card><h2>新建工单</h2><el-form label-position="top" @submit.prevent="guard(create)"><el-form-item label="标题"><el-input v-model="form.title" maxlength="200" required /></el-form-item><el-form-item label="问题描述"><el-input v-model="form.description" type="textarea" :rows="3" required /></el-form-item><div class="options"><el-select v-model="form.category" aria-label="分类"><el-option label="ERP 问题" value="erp"/><el-option label="运维工单" value="operations"/></el-select><el-select v-model="form.priority" aria-label="优先级"><el-option v-for="p in ['low','normal','high','urgent']" :key="p" :label="p" :value="p"/></el-select><el-button type="primary" native-type="submit">提交工单</el-button></div></el-form></el-card>
<el-card><div class="options"><h2>工单列表</h2><el-input v-model="query" placeholder="搜索标题或描述" @keyup.enter="guard(load)"/><el-button @click="guard(load)">搜索</el-button></div><el-table :data="rows" @row-click="(row:Ticket)=>guard(()=>open(row))"><el-table-column prop="id" label="编号" width="90"/><el-table-column prop="title" label="标题"/><el-table-column prop="category" label="分类"/><el-table-column prop="priority" label="优先级"/><el-table-column prop="status" label="状态"/></el-table></el-card>
<el-drawer :model-value="!!selected" title="工单详情" size="min(600px, 100vw)" @close="selected=undefined"><template v-if="selected"><h2>{{selected.title}}</h2><p class="description">{{selected.description}}</p><el-tag>{{selected.status}}</el-tag><div class="options"><el-button v-if="role!=='requester' && ['open','resolved'].includes(selected.status)" @click="guard(()=>transition('in_progress'))">开始处理</el-button><el-button v-if="role!=='requester' && selected.status==='in_progress'" @click="guard(()=>transition('resolved'))">解决</el-button><el-button v-if="selected.status==='resolved'" @click="guard(()=>transition('closed'))">确认关闭</el-button></div><div v-if="role==='admin'" class="options"><el-input-number v-model="assignee" :min="1" aria-label="处理人编号"/><el-button @click="guard(assign)">指派处理人</el-button></div><h3>处理记录</h3><p v-for="event in history" :key="event.id">{{event.message}}</p><el-input v-model="note" type="textarea" placeholder="补充说明"/><el-button @click="guard(comment)">添加评论</el-button></template></el-drawer>
</template></main>
</template>
<style>body{margin:0;background:#f3f6fa;color:#172b46;font-family:system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:32px 20px}header,.options{display:flex;align-items:center;gap:16px;justify-content:space-between}h1{margin:0;color:#2355b5}header{margin-bottom:28px}.el-card{margin-bottom:24px}.login{max-width:420px;margin:60px auto}.options .el-select{width:220px}.description{white-space:pre-wrap}.options{margin:16px 0}h2{font-size:19px;white-space:nowrap}@media(max-width:600px){.options{flex-wrap:wrap}}</style>
