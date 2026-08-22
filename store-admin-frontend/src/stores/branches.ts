import { defineStore } from 'pinia'
import { fetchBranches, addBranch, updateBranch, deleteBranch, type Branch } from '@/api/masterData'

// Shared across the whole session so components that stay mounted across
// navigations (AppSidebar, AppTopbar) reflect branch changes made from the
// settings page without needing a full reload.
export const useBranchStore = defineStore('branches', {
  state: () => ({
    list: [] as Branch[],
    loaded: false,
  }),
  actions: {
    async ensureLoaded() {
      if (this.loaded) return
      await this.load()
    },
    async load() {
      this.list = await fetchBranches()
      this.loaded = true
    },
    async add(nameZh: string, nameJa: string) {
      await addBranch(nameZh, nameJa)
      await this.load()
    },
    async update(id: string, nameZh: string, nameJa: string) {
      await updateBranch(id, nameZh, nameJa)
      await this.load()
    },
    async remove(id: string) {
      await deleteBranch(id)
      await this.load()
    },
  },
})
