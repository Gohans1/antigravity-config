import fs from 'fs';
import path from 'path';
import os from 'os';

const homeDir = os.homedir();
const configDir = path.join(homeDir, '.gemini', 'config');
const globalConfigFile = path.join(configDir, 'config.json');
const projectsDir = path.join(configDir, 'projects');

console.log('=== HOÀN TÁC ANTIGRAVITY AUTO-EXECUTION (TRỞ VỀ YÊU CẦU DUYỆT LỆNH) ===\n');

// 1. Revert Global config.json
if (fs.existsSync(globalConfigFile)) {
  try {
    const raw = fs.readFileSync(globalConfigFile, 'utf8');
    const config = JSON.parse(raw);
    
    config.userSettings = config.userSettings || {};
    config.userSettings.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_OFF';
    
    fs.writeFileSync(globalConfigFile, JSON.stringify(config, null, 2), 'utf8');
    console.log(`[OK] Global config đã đưa về: CASCADE_COMMANDS_AUTO_EXECUTION_OFF`);
  } catch (err) {
    console.error(`[ERROR] Lỗi cập nhật global config: ${err.message}`);
  }
}

// 2. Revert Projects
if (fs.existsSync(projectsDir)) {
  const files = fs.readdirSync(projectsDir).filter(f => f.endsWith('.json'));
  for (const file of files) {
    const filePath = path.join(projectsDir, file);
    try {
      const raw = fs.readFileSync(filePath, 'utf8');
      const proj = JSON.parse(raw);
      
      if (proj.settings) proj.settings.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_OFF';
      proj.autoExecutionPolicy = 'CASCADE_COMMANDS_AUTO_EXECUTION_OFF';
      
      fs.writeFileSync(filePath, JSON.stringify(proj, null, 2), 'utf8');
      console.log(`  + Đã đưa về an toàn cho project: "${proj.name || file}"`);
    } catch (e) {}
  }
}

console.log('\nHOÀN TẤT! Hệ thống đã quay lại chế độ yêu cầu xác nhận trước khi chạy lệnh.');
