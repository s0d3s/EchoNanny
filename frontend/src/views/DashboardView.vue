<template>
  <div class="dashboard">
    <section class="card">
      <h2 class="timeline-title">
        <template v-if="selected && !isActiveSelected">
          <span class="timeline-title-main">Timeline of <strong>#{{ selected.id }}</strong></span>
          <span class="timeline-title-sub">
            {{ formatDate(selected.started_at) }}
            <span class="timeline-dot">•</span>
            <span class="time-chip">{{ formatAudioTime(currentGlobalDurationMs) }}</span>
          </span>
        </template>
        <template v-else>
          <span class="timeline-title-main">Timeline <strong>[Realtime]</strong></span>
          <span v-if="realtimeInfoRecording" class="timeline-title-sub">
            #{{ realtimeInfoRecording.id }}
            <span class="timeline-dot">•</span>
            {{ formatDate(realtimeInfoRecording.started_at) }}
            <span class="timeline-dot">•</span>
            <span class="time-chip">{{ formatAudioTime(currentGlobalDurationMs) }}</span>
          </span>
        </template>
      </h2>
      <TimelineBar
        :duration-ms="currentGlobalDurationMs"
        :segments="globalTimeline.segments"
        :current-ms="playerCurrentMs"
        :show-cursor="isFinishedSelected"
        :interactive="isFinishedSelected"
        @seek="seekSelected"
      />
    </section>

    <div class="grid" ref="gridEl">
    <div class="live-column">
      <section class="card live-monitor-card">
        <div class="live-monitor-layout">
          <div class="live-monitor-top">
            <h2>Live Monitor</h2>

            <div class="live-control-block">
              <p class="live-block-label">Capture controls</p>
              <div class="row live-controls-row">
                <button @click="startLive" :disabled="liveState === 'starting' || liveState === 'live'">Start</button>
                <button @click="stopLive" :disabled="liveState === 'stopping' || liveState === 'idle'">Stop</button>
                <button class="mute-btn" @click="toggleRealtimeMute">{{ mutedRealtime ? 'Unmute realtime' : 'Mute realtime' }}</button>
              </div>
            </div>

            <div class="live-control-block mt8">
              <p class="live-block-label">Input device</p>
              <select class="device-select" v-model="selectedDeviceId" @change="onDeviceSelectionChange">
                <option :value="DEFAULT_DEVICE_OPTION">Default device</option>
                <option v-for="d in devices" :key="d.id" :value="String(d.id)">
                  {{ d.name }}
                </option>
              </select>
            </div>

            <p class="error mt8" v-if="liveError">{{ liveError }}</p>
          </div>

          <div class="live-stats">
            <div class="live-stat-row">
              <span class="muted">Status</span>
              <strong>{{ liveState }}</strong>
            </div>
            <div class="live-stat-row">
              <span class="muted">Jitter queue</span>
              <span>{{ jitterQueue.length }} frames</span>
            </div>
          </div>
        </div>
      </section>

      <section class="card credentials-links-card">
        <div class="credentials-links-content">
          <p class="project-meta muted">© 2026 s0d3s</p>
          <p class="project-meta muted">EchoNanny v{{ APP_VERSION }}</p>
          <a
            class="github-link"
            :href="GITHUB_REPO_URL"
            target="_blank"
            rel="noopener noreferrer"
            title="Open GitHub"
            aria-label="Open GitHub"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.66 7.66 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/>
            </svg>
            <span>GitHub</span>
          </a>
        </div>
      </section>
    </div>

    <section class="card recordings-card" ref="recordingsCardEl">
      <div class="recordings-head-row">
        <h2>Recordings</h2>
        <div class="recordings-search-row">
        <input v-model="search" placeholder="Search path..." />
        <button @click="searchRecordings">Search</button>
        </div>
      </div>
      <ul class="recordings" ref="recordingsListEl" @scroll="onRecordingsScroll">
        <li
          v-for="rec in recordings"
          :key="rec.id"
          @click="selectRecording(rec)"
          :class="{ selected: selected && selected.id === rec.id }"
        >
          <div>
            <strong>#{{ rec.id }}</strong>
            • {{ formatDate(rec.started_at) }}
            • <span class="time-chip">{{ formatAudioTime(durationForRecording(rec)) }}</span>
            • {{ rec.status }}
          </div>
          <TimelineBar
            class="mt8"
            compact
            :duration-ms="recordingTimelineDuration(rec)"
            :segments="recordingTimeline(rec.id).segments"
          />
          <div class="recording-file-row mt8">
            <small>{{ rec.file_path }}</small>
            <button
              class="recording-delete-btn"
              :disabled="rec.status === 'active' || deletingRecordingId === rec.id"
              title="Delete recording"
              @click.stop="openDeleteRecordingModal(rec)"
            >
              🗑️
            </button>
          </div>

        </li>
      </ul>
      <div v-if="recordingsLoadingMore" class="recordings-list-loader" aria-live="polite">
        <div class="recordings-list-spinner" aria-hidden="true"></div>
      </div>
    </section>

    <section class="card" v-if="selected">
      <div class="recording-head">
        <h2
          class="recording-details-title"
          :title="recordingDetailsTitleTooltip(selected)"
        >
          Details of #{{ selected.id }}
        </h2>
        <button class="close-selected-btn" @click="clearSelection">Close</button>
      </div>
      <audio
        class="selected-audio-player"
        ref="player"
        controls
        :src="audioUrl"
        @canplay="onSelectedAudioReady"
        @loadedmetadata="onSelectedAudioReady"
        @error="onSelectedAudioLoadError"
        @timeupdate="onPlayerTimeUpdate"
        @play="isPlaying = true"
        @pause="isPlaying = false"
      ></audio>
      <Transition name="details-fade" mode="out-in">
        <div v-if="selectedDetailsLoading" key="details-loading" class="details-loader-wrap">
          <div class="details-loader-spinner" aria-hidden="true"></div>
          <span class="muted">Loading recording details…</span>
        </div>
        <div v-else key="details-content" class="selected-details-content">
          <div class="labels-list">
            <section v-for="g in groupedLabels" :key="g.type" class="label-group">
              <button class="label-group-head" @click="toggleLabelGroup(g.type)">
                <span class="label-color" :class="g.cssClass"></span>
                <span>{{ g.name }}</span>
                <span class="muted">({{ g.items.length }})</span>
              </button>

              <div v-if="labelExpanded[g.type]" class="label-table">
                <div class="label-table-row label-table-head label-type-head">
                  <span>Length</span>
                  <span>Range</span>
                  <span></span>
                </div>
                <div v-for="l in g.items" :key="l.id" class="label-table-row label-type-row">
                  <span class="time-chip">{{ formatAudioTime(labelDurationMs(l)) }}</span>
                  <span class="time-chip">{{ formatClockTime(l.t_start_ms) }}-{{ formatClockTime(l.t_end_ms) }}</span>
                  <button
                    class="jump-btn"
                    :class="{ 'is-disabled-soft': isActiveSelected }"
                    :disabled="isActiveSelected"
                    @click="playFromLabel(l)"
                  >
                    Play from here
                  </button>
                </div>
              </div>
            </section>
          </div>

          <section class="nearby-labels label-group">
            <button class="label-group-head" @click="toggleNearbyLabels">
              <span>Labels near playback time</span>
              <span class="muted">({{ nearbyLabels.length }})</span>
            </button>
            <div v-if="nearbyExpanded" class="label-table nearby-labels-list">
              <div class="label-table-row label-table-head nearby-head">
                <span>Type</span>
                <span>Length</span>
                <span>Range</span>
                <span></span>
              </div>
              <div v-if="!nearbyLabels.length" class="nearby-labels-empty muted">No nearby labels</div>
              <div v-for="l in nearbyLabels" :key="`near-${l.id}`" class="label-table-row nearby-label-row">
                <div class="nearby-type">
                  <span class="label-color" :class="labelTypeClass(l.label_type)"></span>
                  <span>{{ labelTypeName(l.label_type) }}</span>
                </div>
                <span class="time-chip">{{ formatAudioTime(Math.max(0, l.t_end_ms - l.t_start_ms)) }}</span>
                <span class="time-chip">{{ formatClockTime(l.t_start_ms) }}-{{ formatClockTime(l.t_end_ms) }}</span>
                <button
                  class="jump-btn"
                  :class="{ 'is-disabled-soft': isActiveSelected }"
                  :disabled="isActiveSelected"
                  @click="playFromLabel(l)"
                >
                  Play from here
                </button>
              </div>
            </div>
          </section>
        </div>
      </Transition>
    </section>
    </div>

    <div v-if="deleteModalOpen" class="modal-backdrop" @click.self="cancelDeleteRecording">
      <div class="modal-card">
        <h3 class="modal-title">
          Delete recording #{{ pendingDeleteRecording?.id }}?
        </h3>
        <p class="muted">This will permanently delete the audio file and metadata.</p>
        <p class="error" v-if="deleteError">{{ deleteError }}</p>

        <div class="row mt8 modal-actions-row">
          <button class="modal-cancel-btn" :disabled="deletingRecordingId !== null" @click="cancelDeleteRecording">
            Cancel
          </button>
          <button
            class="recording-delete-confirm-btn"
            :disabled="deletingRecordingId !== null"
            @click="confirmDeleteRecording"
          >
            {{ deletingRecordingId !== null ? 'Deleting...' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import TimelineBar from '../components/TimelineBar.vue'

const APP_VERSION = String(import.meta.env.VITE_APP_VERSION || 'local').trim() || 'local'
const GITHUB_REPO_URL = String(import.meta.env.VITE_GITHUB_REPO_URL || 'https://github.com/').trim() || 'https://github.com/'
const DEFAULT_DEVICE_OPTION = '__default__'

const recordings = ref([])
const activeRecording = ref(null)
const lastActiveRecordingId = ref(null)
const lastRecordingsRefreshAtMs = ref(0)
const selected = ref(null)
const labels = ref([])
const audioUrl = ref('')
const selectedDetailsLabelsLoaded = ref(false)
const selectedDetailsAudioReady = ref(true)
const search = ref('')
const timelines = ref({})
const deleteModalOpen = ref(false)
const pendingDeleteRecording = ref(null)
const deletingRecordingId = ref(null)
const deleteError = ref('')

const devices = ref([])
const selectedDeviceId = ref(DEFAULT_DEVICE_OPTION)
const isApplyingDeviceSelection = ref(false)

const liveState = ref('idle')
const liveError = ref('')
const ws = ref(null)
const mutedRealtime = ref(false)

const audioCtx = ref(null)
const gainNode = ref(null)
const jitterQueue = ref([])
const player = ref(null)
const playerCurrentMs = ref(0)
const isPlaying = ref(false)
const gridEl = ref(null)
const recordingsCardEl = ref(null)
const recordingsListEl = ref(null)

const recordingsLoadingMore = ref(false)
const recordingsHasMore = ref(true)
const recordingsOffset = ref(0)

const globalTimeline = ref({ recording_id: null, duration_ms: 0, is_active: false, segments: [] })
const currentGlobalDurationMs = ref(0)

const activeClockBaseMs = ref(0)
const activeClockSyncedAtMs = ref(0)
const activeDurationMs = ref(0)
const labelExpanded = ref({})
const nearbyExpanded = ref(true)

let pumpTimer = null
let statusTimer = null
let activeClockTimer = null
let nextRealtimePlayAt = 0
let audioUnlockBound = false
let lastRealtimeSampleTail = null
let suppressDeviceSelectionAutoApply = false
let gridResizeObserver = null
let gridLastHeightPx = 0
let gridAnimating = false
let gridPendingHeightPx = 0
let selectedDetailsRequestSeq = 0
let recordingsRequestSeq = 0
let isUnmounting = false
let wsCloseExpected = false

const isFinishedSelected = ref(false)
const isActiveSelected = computed(() => !!selected.value && selected.value.status === 'active')
const NEARBY_LABELS_LIMIT = 10
const RECORDINGS_REFRESH_INTERVAL_MS = 15000
const RECORDINGS_PAGE_LIMIT = 20
const RECORDINGS_PREFETCH_THRESHOLD = 10
const REALTIME_FALLBACK_SAMPLE_RATE = 16000
const REALTIME_MIN_BUFFER_FRAMES = 6
const REALTIME_SCHEDULE_AHEAD_SEC = 0.12
const REALTIME_START_DELAY_SEC = 0.05
const REALTIME_MAX_QUEUE_FRAMES = 80
const REALTIME_BOUNDARY_RAMP_SAMPLES = 12
const realtimeInfoRecording = computed(() => {
  if (selected.value && selected.value.status === 'active') return selected.value
  return activeRecording.value
})

const playbackCursorMs = computed(() =>
  isFinishedSelected.value ? playerCurrentMs.value : currentGlobalDurationMs.value,
)

const selectedDetailsLoading = computed(() => {
  if (!selected.value) return false
  const needsAudioReady = selected.value.status !== 'active'
  return !selectedDetailsLabelsLoaded.value || (needsAudioReady && !selectedDetailsAudioReady.value)
})

const nearbyLabels = computed(() => {
  const items = labels.value || []
  const cursor = Number(playbackCursorMs.value || 0)

  const nearest = [...items]
    .sort((a, b) => {
      const da = labelDistanceToCursor(a, cursor)
      const db = labelDistanceToCursor(b, cursor)
      if (da !== db) return da - db
      return Number(a.t_start_ms || 0) - Number(b.t_start_ms || 0)
    })
    .slice(0, NEARBY_LABELS_LIMIT)

  // Keep all nearest labels first, then group display by type.
  return nearest.sort((a, b) => {
    const lenA = labelDurationMs(a)
    const lenB = labelDurationMs(b)
    if (lenA !== lenB) return lenB - lenA
    return Number(a.t_start_ms || 0) - Number(b.t_start_ms || 0)
  })
})

function labelDurationMs(label) {
  return Math.max(0, Number(label?.t_end_ms || 0) - Number(label?.t_start_ms || 0))
}

function formatDate(v) {
  return new Date(v).toLocaleString()
}

function formatAudioTime(msValue) {
  const ms = Math.max(0, Number(msValue || 0))
  const sec = ms / 1000

  if (sec < 60) {
    return `${sec.toFixed(2).padStart(5, '0')}s`
  }

  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = sec - m * 60
    return `${String(m).padStart(2, '0')}m ${s.toFixed(2).padStart(5, '0')}s`
  }

  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}`
}

function formatClockTime(msValue) {
  const totalSec = Math.max(0, Math.floor((Number(msValue || 0)) / 1000))
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function labelDistanceToCursor(label, cursorMs) {
  const start = Number(label?.t_start_ms || 0)
  const end = Number(label?.t_end_ms || 0)
  if (cursorMs < start) return start - cursorMs
  if (cursorMs > end) return cursorMs - end
  return 0
}

function recordingTimeline(id) {
  return timelines.value[id] || { duration_ms: 0, segments: [] }
}

function labelTypeClass(labelType) {
  if (labelType === 'speech') return 'speech'
  if (labelType === 'noise_event') return 'noise'
  return 'other'
}

function labelTypeName(labelType) {
  return String(labelType || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

function recordingDetailsTitleTooltip(rec) {
  if (!rec) return 'Recording details'
  const sourceName = String(rec.source_device_name || '').trim() || 'Unknown source device'
  return `Source device: ${sourceName}`
}

function orderedTypes(items) {
  const uniq = Array.from(new Set(items.map((l) => l.label_type)))
  return uniq.sort((a, b) => {
    if (a === 'speech' && b !== 'speech') return -1
    if (b === 'speech' && a !== 'speech') return 1
    return a.localeCompare(b)
  })
}

const groupedLabels = computed(() => {
  const result = []
  const types = orderedTypes(labels.value || [])
  for (const type of types) {
    const items = labels.value
      .filter((l) => l.label_type === type)
      .sort((a, b) => {
        const lenA = labelDurationMs(a)
        const lenB = labelDurationMs(b)
        if (lenA !== lenB) return lenB - lenA
        return Number(a.t_start_ms || 0) - Number(b.t_start_ms || 0)
      })

    result.push({
      type,
      name: labelTypeName(type),
      cssClass: labelTypeClass(type),
      items,
    })
  }
  return result
})

function initLabelExpansion() {
  const next = {}
  for (const g of groupedLabels.value) {
    next[g.type] = false
  }
  labelExpanded.value = next
}

function toggleLabelGroup(type) {
  const wasOpen = !!labelExpanded.value[type]
  const next = {}
  for (const key of Object.keys(labelExpanded.value)) {
    next[key] = false
  }
  next[type] = !wasOpen
  labelExpanded.value = next

  const hasAnyExpanded = Object.values(labelExpanded.value).some(Boolean)
  if (hasAnyExpanded) {
    nearbyExpanded.value = false
  }
}

function toggleNearbyLabels() {
  if (nearbyExpanded.value) {
    nearbyExpanded.value = false
    return
  }

  nearbyExpanded.value = true
  const next = {}
  for (const key of Object.keys(labelExpanded.value)) {
    next[key] = false
  }
  labelExpanded.value = next
}

function durationForRecording(rec) {
  if (
    rec
    && rec.status === 'active'
    && activeRecording.value
    && rec.id === activeRecording.value.id
  ) {
    return activeDurationMs.value
  }
  return rec?.duration_ms || 0
}

function recordingTimelineDuration(rec) {
  if (
    rec
    && rec.status === 'active'
    && activeRecording.value
    && rec.id === activeRecording.value.id
  ) {
    return activeDurationMs.value
  }
  return recordingTimeline(rec.id).duration_ms
}

function syncActiveClock(serverDurationMs) {
  const ms = Math.max(0, Number(serverDurationMs || 0))
  activeClockBaseMs.value = ms
  activeClockSyncedAtMs.value = Date.now()
  activeDurationMs.value = ms
}

function tickActiveClock() {
  if (!activeClockSyncedAtMs.value) return
  const delta = Date.now() - activeClockSyncedAtMs.value
  activeDurationMs.value = Math.max(0, activeClockBaseMs.value + delta)

  if (
    activeRecording.value
    && activeRecording.value.status === 'active'
    && (
      !selected.value
      || (selected.value.status === 'active' && selected.value.id === activeRecording.value.id)
    )
  ) {
    currentGlobalDurationMs.value = activeDurationMs.value
  } else {
    currentGlobalDurationMs.value = globalTimeline.value.duration_ms
  }
}

async function syncRealtimeTimelineFromActive() {
  if (!activeRecording.value || activeRecording.value.status !== 'active') {
    globalTimeline.value = { recording_id: null, duration_ms: 0, is_active: false, segments: [] }
    currentGlobalDurationMs.value = 0
    return
  }

  const rec = activeRecording.value
  try {
    timelines.value[rec.id] = await api.timeline(rec.id)
  } catch {
    timelines.value[rec.id] = {
      recording_id: rec.id,
      duration_ms: Math.floor(activeDurationMs.value),
      is_active: true,
      segments: [],
    }
  }

  globalTimeline.value = timelines.value[rec.id]
  currentGlobalDurationMs.value = activeDurationMs.value
}

function mergeUniqueRecordings(base, incoming) {
  if (!incoming.length) return base
  const existingIds = new Set(base.map((item) => item.id))
  const merged = [...base]
  for (const item of incoming) {
    if (!existingIds.has(item.id)) {
      merged.push(item)
      existingIds.add(item.id)
    }
  }
  return merged
}

async function ensureTimelinesForFinishedRecordings(items) {
  const finished = items.filter((r) => r.status !== 'active')
  await Promise.all(
    finished.map(async (rec) => {
      // Finished timelines are immutable enough for list rendering,
      // so fetch once and reuse cache instead of polling repeatedly.
      if (timelines.value[rec.id] && timelines.value[rec.id].is_active === false) {
        return
      }
      try {
        timelines.value[rec.id] = await api.timeline(rec.id)
      } catch {
        timelines.value[rec.id] = { recording_id: rec.id, duration_ms: rec.duration_ms, is_active: false, segments: [] }
      }
    }),
  )
}

function onRecordingsScroll() {
  const el = recordingsListEl.value
  if (!el) return

  if (!recordingsHasMore.value || recordingsLoadingMore.value) return

  const rows = el.querySelectorAll('li')
  const sampleCount = Math.min(5, rows.length)
  const avgRowHeight = sampleCount > 0
    ? Array.from(rows).slice(0, sampleCount).reduce((sum, row) => sum + row.getBoundingClientRect().height, 0) / sampleCount
    : 56
  const remainingPx = el.scrollHeight - (el.scrollTop + el.clientHeight)
  const prefetchPx = Math.max(140, avgRowHeight * RECORDINGS_PREFETCH_THRESHOLD)

  if (remainingPx <= prefetchPx) {
    loadMoreRecordings()
  }
}

async function loadRecordings({ append = false, resetPagination = false } = {}) {
  if (append && (recordingsLoadingMore.value || !recordingsHasMore.value)) return

  const reqId = ++recordingsRequestSeq
  const offset = resetPagination ? 0 : (append ? recordingsOffset.value : 0)
  const requestedLimit = RECORDINGS_PAGE_LIMIT

  if (append) {
    recordingsLoadingMore.value = true
  }

  try {
    const chunk = await api.recordings({
      query: search.value,
      limit: requestedLimit,
      offset,
    })

    if (reqId !== recordingsRequestSeq) return

    if (append) {
      recordings.value = mergeUniqueRecordings(recordings.value, chunk)
      recordingsOffset.value += chunk.length
    } else {
      recordings.value = chunk
      recordingsOffset.value = chunk.length
    }

    recordingsHasMore.value = chunk.length === requestedLimit

    await ensureTimelinesForFinishedRecordings(append ? chunk : recordings.value)

  } finally {
    if (append) {
      recordingsLoadingMore.value = false
    }
  }
}

async function loadMoreRecordings() {
  await loadRecordings({ append: true })
}

async function searchRecordings() {
  recordingsHasMore.value = true
  recordingsOffset.value = 0
  await loadRecordings({ resetPagination: true })
}

async function selectRecording(rec) {
  const reqId = ++selectedDetailsRequestSeq
  selected.value = rec
  applyAutoRealtimeMuteForSelection(rec)
  isFinishedSelected.value = rec.status !== 'active'
  isPlaying.value = false
  playerCurrentMs.value = 0
  selectedDetailsLabelsLoaded.value = false
  selectedDetailsAudioReady.value = rec.status === 'active'
  labels.value = []
  nearbyExpanded.value = true
  initLabelExpansion()

  if (!timelines.value[rec.id]) {
    try {
      timelines.value[rec.id] = await api.timeline(rec.id)
    } catch {
      timelines.value[rec.id] = { recording_id: rec.id, duration_ms: rec.duration_ms, is_active: rec.status === 'active', segments: [] }
    }
  }
  globalTimeline.value = timelines.value[rec.id]
  currentGlobalDurationMs.value = rec.status === 'active' ? activeDurationMs.value : globalTimeline.value.duration_ms

  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
    audioUrl.value = ''
  }

  if (rec.status !== 'active') {
    try {
      const blob = await api.recordingFileBlob(rec.id)
      if (reqId !== selectedDetailsRequestSeq || !selected.value || selected.value.id !== rec.id) return
      audioUrl.value = URL.createObjectURL(blob)
    } catch {
      if (reqId === selectedDetailsRequestSeq) {
        selectedDetailsAudioReady.value = true
      }
    }
  }

  try {
    const nextLabels = await api.labels(rec.id)
    if (reqId !== selectedDetailsRequestSeq || !selected.value || selected.value.id !== rec.id) return
    labels.value = nextLabels
    initLabelExpansion()
  } finally {
    if (reqId === selectedDetailsRequestSeq) {
      selectedDetailsLabelsLoaded.value = true
    }
  }

}

async function playFromLabel(label) {
  if (!selected.value || selected.value.status === 'active') return
  if (!audioUrl.value) {
    const blob = await api.recordingFileBlob(selected.value.id)
    audioUrl.value = URL.createObjectURL(blob)
  }
  await nextTick()
  if (!player.value) return
  player.value.currentTime = label.t_start_ms / 1000
  playerCurrentMs.value = label.t_start_ms
  await player.value.play()
}

async function startLive() {
  liveState.value = 'starting'
  liveError.value = ''
  try {
    const resp = await api.startLive()
    const startedRecordingId = resp?.recording_id ?? null
    await connectWs()
    liveState.value = 'live'

    await loadRecordings()

    if (startedRecordingId) {
      const started = recordings.value.find((r) => r.id === startedRecordingId)
      if (started) {
        activeRecording.value = started
        if (!selected.value || (selected.value && selected.value.status !== 'active')) {
          await selectRecording(started)
        }
      }
    }
  } catch (e) {
    liveError.value = e.message || 'Failed to start live stream'
    liveState.value = 'error'
  }
}

async function stopLive() {
  liveState.value = 'stopping'
  let stoppedRecordingId = null
  try {
    const resp = await api.stopLive()
    stoppedRecordingId = resp?.recording_id ?? null
  } catch {
    // no-op
  }

  disconnectLiveSocketOnly()
  liveState.value = 'idle'

  if (stoppedRecordingId) {
    await refreshStoppedRecording(stoppedRecordingId)
  } else {
    await loadRecordings()
  }

  await refreshLiveStatus()
}

async function refreshStoppedRecording(recordingId) {
  await loadRecordings({ resetPagination: true })

  const updated = recordings.value.find((r) => r.id === recordingId)
  if (!updated) return

  // Refresh timeline with final duration/labels and make it immediately playable.
  try {
    timelines.value[recordingId] = await api.timeline(recordingId)
  } catch {
    // ignore
  }

  if (selected.value && selected.value.id === recordingId) {
    await selectRecording(updated)
  }
}

function disconnectLiveSocketOnly() {
  wsCloseExpected = true
  resetRealtimePlaybackState({ closeSocket: true, clearQueue: true })
}

function resetRealtimePlaybackState({ closeSocket = false, clearQueue = false } = {}) {
  if (closeSocket && ws.value) {
    ws.value.close()
    ws.value = null
  }

  if (clearQueue) {
    jitterQueue.value = []
  }

  nextRealtimePlayAt = 0
  lastRealtimeSampleTail = null

  if (!ws.value) {
    clearInterval(pumpTimer)
    pumpTimer = null
  }
}

function getRealtimeSampleRate() {
  const sr = Number(
    realtimeInfoRecording.value?.sample_rate
    || activeRecording.value?.sample_rate
    || REALTIME_FALLBACK_SAMPLE_RATE,
  )
  if (!Number.isFinite(sr) || sr <= 0) return REALTIME_FALLBACK_SAMPLE_RATE
  return Math.round(sr)
}

async function tryResumeAudioContext() {
  if (!audioCtx.value) return false
  if (audioCtx.value.state === 'running') return true
  try {
    await audioCtx.value.resume()
    return audioCtx.value.state === 'running'
  } catch {
    return false
  }
}

function bindAudioUnlockHandlers() {
  if (audioUnlockBound) return
  audioUnlockBound = true

  const unlock = async () => {
    await tryResumeAudioContext()
    if (audioCtx.value && audioCtx.value.state === 'running') {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }

  window.addEventListener('pointerdown', unlock)
  window.addEventListener('keydown', unlock)
}

async function connectWs() {
  if (ws.value && (ws.value.readyState === WebSocket.OPEN || ws.value.readyState === WebSocket.CONNECTING)) {
    return
  }

  if (!audioCtx.value) {
    audioCtx.value = new AudioContext()
    gainNode.value = audioCtx.value.createGain()
    gainNode.value.connect(audioCtx.value.destination)
    bindAudioUnlockHandlers()
  }
  await tryResumeAudioContext()

  resetRealtimePlaybackState({ closeSocket: false, clearQueue: true })
  wsCloseExpected = false

  ws.value = new WebSocket(api.wsLiveUrl())
  ws.value.binaryType = 'arraybuffer'

  ws.value.onmessage = (ev) => {
    if (typeof ev.data === 'string') return
    jitterQueue.value.push(new Int16Array(ev.data))
    if (jitterQueue.value.length > REALTIME_MAX_QUEUE_FRAMES) {
      jitterQueue.value.splice(0, jitterQueue.value.length - REALTIME_MAX_QUEUE_FRAMES)
    }
  }

  ws.value.onclose = () => {
    const expectedClose = wsCloseExpected || isUnmounting
    wsCloseExpected = false
    ws.value = null
    resetRealtimePlaybackState({ closeSocket: false, clearQueue: true })
    if (!expectedClose && liveState.value === 'live') {
      liveState.value = 'idle'
    }
  }

  ws.value.onerror = () => {
    if (wsCloseExpected || isUnmounting) return
    liveError.value = 'WebSocket error'
    if (liveState.value === 'live') {
      liveState.value = 'idle'
    }
  }

  if (!pumpTimer) {
    pumpTimer = setInterval(pumpJitterBuffer, 20)
  }
}

function pumpJitterBuffer() {
  if (!audioCtx.value) return
  if (audioCtx.value.state !== 'running') return
  if (jitterQueue.value.length < REALTIME_MIN_BUFFER_FRAMES) return

  const realtimeSampleRate = getRealtimeSampleRate()

  const now = audioCtx.value.currentTime

  if (nextRealtimePlayAt <= 0) {
    nextRealtimePlayAt = now + REALTIME_START_DELAY_SEC
  }

  while (jitterQueue.value.length > 0 && nextRealtimePlayAt < now + REALTIME_SCHEDULE_AHEAD_SEC) {
    const frameBatchSize = Math.min(5, jitterQueue.value.length)
    if (frameBatchSize <= 0) break

    const frames = jitterQueue.value.splice(0, frameBatchSize)
    const totalSamples = frames.reduce((sum, f) => sum + f.length, 0)
    if (totalSamples <= 0) continue

    const buffer = audioCtx.value.createBuffer(1, totalSamples, realtimeSampleRate)
    const chan = buffer.getChannelData(0)

    let offset = 0
    for (const frame of frames) {
      for (let i = 0; i < frame.length; i += 1) {
        chan[offset + i] = frame[i] / 32768
      }
      offset += frame.length
    }

    // Non-overlapping de-click at batch boundaries.
    if (lastRealtimeSampleTail !== null && totalSamples > 0) {
      const delta = lastRealtimeSampleTail - chan[0]
      if (Math.abs(delta) > 0.002) {
        const rampLen = Math.min(REALTIME_BOUNDARY_RAMP_SAMPLES, totalSamples)
        const denom = Math.max(1, rampLen - 1)
        for (let i = 0; i < rampLen; i += 1) {
          const t = i / denom
          chan[i] = Math.max(-1, Math.min(1, chan[i] + delta * (1 - t)))
        }
      }
    }

    if (totalSamples > 0) {
      lastRealtimeSampleTail = chan[totalSamples - 1]
    }

    const src = audioCtx.value.createBufferSource()
    src.buffer = buffer
    if (gainNode.value) {
      src.connect(gainNode.value)
    } else {
      src.connect(audioCtx.value.destination)
    }

    const scheduledAt = Math.max(nextRealtimePlayAt, audioCtx.value.currentTime + 0.005)
    src.start(scheduledAt)
    nextRealtimePlayAt = scheduledAt + buffer.duration
  }

  // Guard against drift after long stalls (tab suspended / CPU spike).
  if (nextRealtimePlayAt > 0 && now - nextRealtimePlayAt > 0.5) {
    nextRealtimePlayAt = now + REALTIME_START_DELAY_SEC
    lastRealtimeSampleTail = null
  }
}

function toggleRealtimeMute() {
  setRealtimeMuted(!mutedRealtime.value)
}

function setRealtimeMuted(shouldMute) {
  mutedRealtime.value = !!shouldMute
  if (gainNode.value) {
    gainNode.value.gain.value = mutedRealtime.value ? 0 : 1
  }
}

function applyAutoRealtimeMuteForSelection(rec) {
  const shouldMute = !!rec && rec.status !== 'active'
  setRealtimeMuted(shouldMute)
}

async function loadDevices() {
  devices.value = await api.devices()
}

async function applyDeviceSelection(deviceValue) {
  if (isApplyingDeviceSelection.value) return

  const normalized = typeof deviceValue === 'string' ? deviceValue : String(deviceValue ?? DEFAULT_DEVICE_OPTION)
  const parsed = normalized === DEFAULT_DEVICE_OPTION ? null : Number(normalized)
  const nextDeviceId = Number.isNaN(parsed) ? null : parsed

  const preferredFromStatus = (() => {
    if (!activeRecording.value) return null
    const current = activeRecording.value.selected_device
    if (current === undefined || current === null || current === '' || current === 'default') return null
    const n = Number(current)
    return Number.isNaN(n) ? null : n
  })()
  const normalizedFromStatus = preferredFromStatus === null ? DEFAULT_DEVICE_OPTION : String(preferredFromStatus)
  if (normalized === normalizedFromStatus && !activeRecording.value?.id) {
    return
  }

  isApplyingDeviceSelection.value = true
  try {
    // Device reconfigure on backend may stop+start the stream.
    // The existing websocket can stay connected to the old session,
    // so force reconnect to resubscribe to the new active session.
    disconnectLiveSocketOnly()

    await api.configureLive(nextDeviceId)

    await refreshLiveStatus()
    await loadRecordings()
    lastRecordingsRefreshAtMs.value = Date.now()

    if (selected.value) {
      const refreshedSelected = recordings.value.find((r) => r.id === selected.value.id)
      if (refreshedSelected) {
        await selectRecording(refreshedSelected)
      } else if (selected.value.status === 'active') {
        const refreshedActive = recordings.value.find((r) => r.status === 'active')
        if (refreshedActive) {
          await selectRecording(refreshedActive)
        } else {
          await clearSelection()
        }
      }
    }
  } catch (e) {
    liveError.value = e.message || 'Failed to apply device'
  } finally {
    isApplyingDeviceSelection.value = false
  }
}

async function onDeviceSelectionChange() {
  await applyDeviceSelection(selectedDeviceId.value)
}

function seekSelected(ms) {
  if (!player.value || !isFinishedSelected.value) return
  player.value.currentTime = ms / 1000
  playerCurrentMs.value = ms
}

function togglePlayback() {
  if (!player.value || !isFinishedSelected.value) return
  if (player.value.paused) {
    player.value.play()
  } else {
    player.value.pause()
  }
}

async function refreshLiveStatus() {
  try {
    const status = await api.liveStatus()
    if (status.is_active) {
      liveState.value = 'live'
      syncActiveClock(status.duration_ms)
      if (!ws.value) {
        await connectWs()
      }
    } else if (liveState.value !== 'error') {
      liveState.value = 'idle'
    }
    if (status.last_error) {
      liveError.value = status.last_error
    }
    if (status.selected_device !== null && status.selected_device !== undefined) {
      suppressDeviceSelectionAutoApply = true
      selectedDeviceId.value = String(status.selected_device)
      suppressDeviceSelectionAutoApply = false
    } else {
      suppressDeviceSelectionAutoApply = true
      selectedDeviceId.value = DEFAULT_DEVICE_OPTION
      suppressDeviceSelectionAutoApply = false
    }
  } catch {
    // ignore transient polling failures
  }

  try {
    const prevActiveId = lastActiveRecordingId.value
    activeRecording.value = await api.activeRecording()
    const nextActiveId = activeRecording.value?.id ?? null

    if (prevActiveId !== nextActiveId) {
      lastActiveRecordingId.value = nextActiveId
      await loadRecordings()
      lastRecordingsRefreshAtMs.value = Date.now()

      if (selected.value) {
        const refreshedSelected = recordings.value.find((r) => r.id === selected.value.id)
        if (refreshedSelected) {
          selected.value = refreshedSelected
        }
      }
    }

    if (activeRecording.value && activeRecording.value.status === 'active') {
      activeRecording.value.duration_ms = Math.floor(activeDurationMs.value)
    }

    const now = Date.now()
    if (now - lastRecordingsRefreshAtMs.value >= RECORDINGS_REFRESH_INTERVAL_MS) {
      await loadRecordings()
      lastRecordingsRefreshAtMs.value = now
    }

    if (!selected.value) {
      await syncRealtimeTimelineFromActive()
    }
  } catch {
    activeRecording.value = null
    if (lastActiveRecordingId.value !== null) {
      lastActiveRecordingId.value = null
      await loadRecordings()
      lastRecordingsRefreshAtMs.value = Date.now()
    }
  }
}

async function clearSelection() {
  selectedDetailsRequestSeq += 1
  selected.value = null
  isFinishedSelected.value = false
  isPlaying.value = false
  playerCurrentMs.value = 0
  labels.value = []
  selectedDetailsLabelsLoaded.value = true
  selectedDetailsAudioReady.value = true
  applyAutoRealtimeMuteForSelection(activeRecording.value)

  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
    audioUrl.value = ''
  }

  await syncRealtimeTimelineFromActive()
}

function onSelectedAudioReady() {
  selectedDetailsAudioReady.value = true
}

function onSelectedAudioLoadError() {
  selectedDetailsAudioReady.value = true
}

function openDeleteRecordingModal(rec) {
  if (!rec || rec.status === 'active') return
  pendingDeleteRecording.value = rec
  deleteError.value = ''
  deleteModalOpen.value = true
}

function cancelDeleteRecording() {
  if (deletingRecordingId.value !== null) return
  deleteModalOpen.value = false
  pendingDeleteRecording.value = null
  deleteError.value = ''
}

async function confirmDeleteRecording() {
  const rec = pendingDeleteRecording.value
  if (!rec) return

  deletingRecordingId.value = rec.id
  deleteError.value = ''

  try {
    await api.deleteRecording(rec.id)

    if (selected.value && selected.value.id === rec.id) {
      await clearSelection()
    }

    if (activeRecording.value && activeRecording.value.id === rec.id) {
      activeRecording.value = null
    }

    delete timelines.value[rec.id]
    recordings.value = recordings.value.filter((r) => r.id !== rec.id)

    deleteModalOpen.value = false
    pendingDeleteRecording.value = null
    await loadRecordings()
    lastRecordingsRefreshAtMs.value = Date.now()
  } catch (e) {
    deleteError.value = e.message || 'Failed to delete recording'
  } finally {
    deletingRecordingId.value = null
  }
}

async function returnToActive() {
  if (!activeRecording.value) return
  await selectRecording(activeRecording.value)
}

function onPlayerTimeUpdate() {
  playerCurrentMs.value = Math.floor((player.value?.currentTime || 0) * 1000)
}

function animateGridHeightTo(nextHeightPx) {
  const el = gridEl.value
  if (!el) return

  const next = Math.max(0, Number(nextHeightPx || 0))
  if (!Number.isFinite(next)) return

  if (gridAnimating) {
    gridPendingHeightPx = next
    return
  }

  const from = gridLastHeightPx || el.getBoundingClientRect().height
  if (Math.abs(next - from) < 1) {
    gridLastHeightPx = next
    return
  }

  gridAnimating = true

  el.style.height = `${from}px`
  el.style.overflow = 'hidden'
  el.style.transition = 'height 220ms ease'
  // Force style flush before changing to the target height.
  void el.offsetHeight

  requestAnimationFrame(() => {
    el.style.height = `${next}px`
  })

  const onTransitionEnd = (event) => {
    if (event.propertyName !== 'height') return
    el.removeEventListener('transitionend', onTransitionEnd)

    el.style.transition = ''
    el.style.height = ''
    el.style.overflow = ''

    gridAnimating = false
    gridLastHeightPx = next

    if (Math.abs(gridPendingHeightPx - gridLastHeightPx) >= 1) {
      const pending = gridPendingHeightPx
      gridPendingHeightPx = 0
      animateGridHeightTo(pending)
    }
  }

  el.addEventListener('transitionend', onTransitionEnd)
}

function syncRecordingsCardHeight() {
  const grid = gridEl.value
  const recordingsCard = recordingsCardEl.value
  if (!grid || !recordingsCard) return

  const items = Array.from(grid.children)
  const peers = items.filter((item) => item !== recordingsCard)
  if (!peers.length) {
    recordingsCard.style.height = ''
    return
  }

  const target = Math.max(...peers.map((item) => item.getBoundingClientRect().height))
  if (!Number.isFinite(target) || target <= 0) return

  recordingsCard.style.height = `${target}px`
}

onMounted(async () => {
  activeClockTimer = setInterval(tickActiveClock, 100)

  if (gridEl.value) {
    syncRecordingsCardHeight()
    gridLastHeightPx = gridEl.value.getBoundingClientRect().height
    gridResizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      syncRecordingsCardHeight()
      animateGridHeightTo(entry.contentRect.height)
    })
    gridResizeObserver.observe(gridEl.value)
  }

  await loadDevices()
  await refreshLiveStatus()
  await loadRecordings({ resetPagination: true })
  statusTimer = setInterval(async () => {
    await refreshLiveStatus()
    // Poll labels/timeline only for ACTIVE selected recording.
    // Finished recordings should not be polled continuously.
    if (selected.value && selected.value.status === 'active') {
      try {
        timelines.value[selected.value.id] = await api.timeline(selected.value.id)
        globalTimeline.value = timelines.value[selected.value.id]

        labels.value = await api.labels(selected.value.id)
      } catch {
        // ignore
      }
    }
  }, 3000)
})

onBeforeUnmount(() => {
  isUnmounting = true
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
  }

  if (gridResizeObserver) {
    gridResizeObserver.disconnect()
    gridResizeObserver = null
  }

  clearInterval(statusTimer)
  clearInterval(activeClockTimer)
  disconnectLiveSocketOnly()
})
</script>
