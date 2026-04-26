<template>
  <div
    class="timeline"
    :class="{ interactive, compact }"
    role="slider"
    :aria-disabled="!interactive"
    @click="onClick"
  >
    <div
      v-for="(s, idx) in normalized"
      :key="`${s.label_type}-${s.t_start_ms}-${idx}`"
      class="segment"
      :class="segmentClass(s.label_type)"
      :style="segmentStyle(s)"
      :title="`${s.label_type}: ${s.t_start_ms}ms - ${s.t_end_ms}ms`"
    />
    <div v-if="showCursor" class="cursor" :style="cursorStyle" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  durationMs: { type: Number, default: 0 },
  segments: { type: Array, default: () => [] },
  currentMs: { type: Number, default: 0 },
  interactive: { type: Boolean, default: false },
  showCursor: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['seek'])

const safeDuration = computed(() => Math.max(1, props.durationMs || 1))
const normalized = computed(() =>
  (props.segments || []).filter((s) => Number.isFinite(s.t_start_ms) && Number.isFinite(s.t_end_ms) && s.t_end_ms >= s.t_start_ms),
)

const cursorStyle = computed(() => {
  const ratio = Math.min(1, Math.max(0, (props.currentMs || 0) / safeDuration.value))
  return { left: `${ratio * 100}%` }
})

function segmentStyle(seg) {
  const start = Math.min(1, Math.max(0, seg.t_start_ms / safeDuration.value))
  const end = Math.min(1, Math.max(0, seg.t_end_ms / safeDuration.value))
  return {
    left: `${start * 100}%`,
    width: `${Math.max(0.2, (end - start) * 100)}%`,
  }
}

function segmentClass(label) {
  if (label === 'speech') return 'speech'
  if (label === 'noise_event') return 'noise'
  return 'other'
}

function onClick(ev) {
  if (!props.interactive) return
  const rect = ev.currentTarget.getBoundingClientRect()
  const ratio = (ev.clientX - rect.left) / rect.width
  emit('seek', Math.floor(Math.max(0, Math.min(1, ratio)) * safeDuration.value))
}
</script>
