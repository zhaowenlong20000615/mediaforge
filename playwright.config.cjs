const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'tests/browser',workers:1,timeout:120000,expect:{timeout:15000},fullyParallel:false,
  use:{baseURL:process.env.MF_BROWSER_URL||'http://127.0.0.1:28086/',browserName:'chromium',viewport:{width:1440,height:1000},screenshot:'only-on-failure',trace:'off',video:'off'},
  reporter:[['list'],['json',{outputFile:'var/audit-oct6/browser-results.json'}]],outputDir:'var/audit-oct6/browser-artifacts'});
