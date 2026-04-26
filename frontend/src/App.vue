<template>
  <div class="app">
    <header class="topbar">
      <h1>EchoNanny</h1>
      <button v-if="hasToken()" @click="logout">Logout</button>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { clearTokens } from './api'

const router = useRouter()

function hasToken() {
  return !!localStorage.getItem('access_token')
}

function logout() {
  clearTokens()
  router.push('/login')
}
</script>
