<script setup lang="ts">
/**
 * Minimal line-icon set (24x24, 1.5px stroke). No emoji anywhere in the UI.
 */
const props = withDefaults(
  defineProps<{ name: string; size?: number; strokeWidth?: number }>(),
  { size: 16, strokeWidth: 1.5 },
)

const paths: Record<string, string> = {
  headphones:
    'M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v6H5a1 1 0 0 1-1-1v-5Zm16 0h-3v6h2a1 1 0 0 0 1-1v-5Z',
  library: 'M4 5h5v15H4zM11 5h4v15h-4zM17 6l3.2-.9 2.1 14.2-3.2.9z',
  chart: 'M4 20V10m5 10V4m5 16v-7m5 7V7',
  settings:
    'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm8-3.5a8 8 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a8 8 0 0 0-2-1.2L15.1 3h-4l-.4 2.6a8 8 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a8 8 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a8 8 0 0 0 2 1.2l.4 2.6h4l.4-2.6a8 8 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 2v2m0 16v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M2 12h2m16 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z',
  plus: 'M12 5v14M5 12h14',
  search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm5-1.5L20 20',
  trash: 'M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6',
  check: 'M4 12.5 9.5 18 20 6',
  close: 'M6 6l12 12M18 6 6 18',
  arrowLeft: 'M20 12H4m6-7-7 7 7 7',
  chevronRight: 'm9 5 7 7-7 7',
  play: 'M7 4.5v15l13-7.5-13-7.5Z',
  pause: 'M8 4v16M16 4v16',
  rewind: 'M11 12 21 5v14l-10-7ZM3 5v14',
  forward: 'M13 12 3 5v14l10-7ZM21 5v14',
  repeat: 'M4 10V8a3 3 0 0 1 3-3h10m0 0-3-3m3 3-3 3M20 14v2a3 3 0 0 1-3 3H7m0 0 3 3m-3-3 3-3',
  volume: 'M4 9v6h4l5 4V5L8 9H4Zm12-1a5 5 0 0 1 0 8',
  edit: 'M4 20h4L20 8l-4-4L4 16v4ZM14 6l4 4',
  refresh: 'M20 11a8 8 0 1 0-1 5M20 4v7h-7',
  eye: 'M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Zm10 2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
  translate: 'M3 5h9M7.5 5v2c0 4-2 7-4.5 8m2-5c1 3 3 5 6 6m-1-9h7m-3.5 0c0 5 1.5 8 3.5 10m-8-4 4 9m4-9-4 9',
  mic: 'M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm-6-4a6 6 0 0 0 12 0M12 17v4m-3 0h6',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v5l3 2',
  upload: 'M12 16V4m0 0L7 9m5-5 5 5M4 17v3h16v-3',
  file: 'M6 3h8l4 4v14H6V3Zm8 0v4h4',
  spark: 'M12 3v4m0 10v4M3 12h4m10 0h4M5.6 5.6l2.8 2.8m7.2 7.2 2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8',
  alert: 'M12 4 2.5 20h19L12 4Zm0 5v6m0 3v.5',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v.5m0 3v6',
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.5M3 12h.5M3 18h.5',
  flag: 'M5 21V4m0 0h11l-1.5 4L16 12H5',
  pencil: 'M4 20h4L20 8l-4-4L4 16v4Zm10-14 4 4',
  book: 'M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Zm2 13h12',
  headphonesOff:
    'M4 14v-2a8 8 0 0 1 13.3-6M20 14v-2c0-1-.2-2-.5-2.9M4 14h3v6H5a1 1 0 0 1-1-1v-5Zm16 0h-3v6h2a1 1 0 0 0 1-1v-5ZM3 3l18 18',
}

const d = props.name in paths ? paths[props.name] : paths.info
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="d" />
  </svg>
</template>

<style scoped>
.icon {
  display: inline-block;
  vertical-align: -0.15em;
  flex-shrink: 0;
}
</style>
