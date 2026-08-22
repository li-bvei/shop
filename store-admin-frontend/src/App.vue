<script setup lang="ts">
import { RouterView } from 'vue-router'
import { useElLocale } from '@/locale/elLocale'

const elLocale = useElLocale()
</script>

<template>
  <el-config-provider :locale="elLocale">
    <RouterView />
  </el-config-provider>
</template>
