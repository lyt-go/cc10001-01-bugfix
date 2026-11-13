<template>
  <section class="page" data-module="datasource">
    <header class="page-head">
      <div>
        <h2>采集源登记管理</h2>
        <p class="page-desc">维护待采集数据源的注册、连通性探测与生命周期管理，确保每个采集源有可验证的接入配置。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记采集源</button>
        <button class="btn" type="button" @click="exportRows">导出采集源登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <span v-if="!row.status" class="muted-text">状态缺失</span>
            <span v-else-if="!allowedActions(row).length" class="muted-text">已归档，不可再流转</span>
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集源登记数据，可先登记采集源</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集源登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/datasource'
const columns = ["源端编号", "目标域名", "入口URL", "请求方式", "字符编码", "访问频率", "超时秒数", "归属项目"]
// 状态序列与服务层一致：列表只展示能推进到直接后继状态的动作，跳级与倒序按钮不会出现。
const STATUS_ORDER = ['草稿', '连通测试中', '已上线', '已归档']
const ACTIONS = ['发起连通测试', '标记上线', '归档源配置']
const stats = [{"label": "采集源总数", "value": 0}, {"label": "已上线采集源", "value": 0}, {"label": "连通测试中", "value": 0}]

/** 动作的目标状态，与服务层 ACTION_RULES 一一对应。 */
function actionTarget(action: string): string | null {
  if (action === '发起连通测试') return '连通测试中'
  if (action === '标记上线') return '已上线'
  if (action === '归档源配置') return '已归档'
  return null
}

/** 当前状态可执行的动作：只允许推进到严格后继；已归档为终态，不展示任何动作。 */
function allowedActions(row: Row): string[] {
  const current = STATUS_ORDER.indexOf(String(row.status ?? ''))
  if (current < 0) return []
  return ACTIONS.filter((action) => {
    const target = actionTarget(action)
    return target !== null && STATUS_ORDER.indexOf(target) === current + 1
  })
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '采集源登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    // 后端约定动作接口返回 { ok, message, entry }：以落库结果为准，不能用 HTTP 200 当作成功。
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      errorMessage.value = payload?.message ?? '采集源登记动作未生效，请稍后重试'
      await reload()
      return
    }
    errorMessage.value = ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集源登记操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('采集源列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集源登记列表读取失败'
  }
}

onMounted(reload)
</script>
