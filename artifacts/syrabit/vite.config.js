import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  oxc: {
    include: /\.(m?[jt]sx?)$/,
    exclude: /node_modules/,
    lang: 'jsx',
    jsx: {
      runtime: 'automatic',
      importSource: 'react',
    },
  },

  plugins: [
    react({
      include: /\.(js|jsx|ts|tsx)$/,
    }),
  ],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    extensions: ['.js', '.jsx', '.ts', '.tsx'],
  },

  server: {
    port: 5000,
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/docs': { target: 'http://localhost:8000', changeOrigin: true },
      '/openapi.json': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },

  define: {
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'development'),
  },

  esbuild: {
    target: 'esnext',
    logOverride: { 'this-is-undefined-in-esm': 'silent' },
  },

  build: {
    outDir: 'build',
    sourcemap: false,
    target: 'esnext',
    minify: 'esbuild',
    cssMinify: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          router: ['react-router-dom'],
          query: ['@tanstack/react-query'],
          motion: ['framer-motion'],
          charts: ['recharts'],
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },

  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react/jsx-dev-runtime',
      'react/jsx-runtime',
      'react-router-dom',
      '@tanstack/react-query',
      'framer-motion',
      'react-markdown',
      'remark-gfm',
    ],
    needsInterop: [
      'react',
      'react-dom',
      'react/jsx-dev-runtime',
      'react/jsx-runtime',
    ],
    extensions: ['.js', '.jsx'],
    rolldownOptions: {
      moduleTypes: { '.js': 'jsx' },
    },
  },
});
