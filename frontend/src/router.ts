import { createRouter, createWebHashHistory } from 'vue-router'
import { ref } from 'vue'

export const toast = ref<{ text: string; kind: 'info' | 'error' } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null

export function showToast(text: string, kind: 'info' | 'error' = 'info', ms = 4000) {
  toast.value = { text, kind }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = null
    toastTimer = null
  }, ms)
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'library', component: () => import('./views/LibraryView.vue') },
    { path: '/practice/:setId', name: 'practice', component: () => import('./views/PracticeView.vue') },
    { path: '/material/:materialId', name: 'material', component: () => import('./views/MaterialView.vue') },
    { path: '/paper/:materialId', name: 'paper', component: () => import('./views/PaperView.vue') },
    { path: '/review', name: 'review', component: () => import('./views/ReviewView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
