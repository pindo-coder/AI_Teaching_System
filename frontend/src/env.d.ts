/// <reference types="vite/client" />

import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    roles?: Array<'student' | 'teacher' | 'admin'>
  }
}
