import fs from 'fs';
import path from 'path';
import os from 'os';

const homeDir = os.homedir();
const configDir = path.join(homeDir, '.gemini', 'config');
const globalConfigFile = path.join(configDir, 'config.json');
const projectsDir = path.join(configDir, 'projects');

console.log('=== KIỂM TRA TRẠNG THÁI ANTIGRAVITY AUTO-EXECUTION ===\n');

if (fs.existsSync(globalConfigFile)) {
  try {
    const config = JSON.parse(fs.readFileSync(globalConfigFile, 'utf8'));
    const policy = config.userSettings?.autoExecutionPolicy || 'CHƯA THIẾT LẬP (Mặc định: OFF)';
    const isEager = policy === 'CASCADE_COMMANDS_AUTO_EXECUTION_EAGER';
    console.log(`Global Policy: [ ${policy} ] -> ${isEager ? '🟢 ĐANG BẬT TỰ ĐỘNG (EAGER)' : '🔴 ĐANG CHẶN HỎI XÁC NHẬN'}`);
  } catch (e) {
    console.error(`Lỗi đọc global config: ${e.message}`);
  }
}

if (fs.existsSync(projectsDir)) {
  console.log('\nChi tiết các dự án:');
  const files = fs.readdirSync(projectsDir).filter(f => f.endsWith('.json'));
  for (const file of files) {
    try {
      const proj = JSON.parse(fs.readFileSync(path.join(projectsDir, file), 'utf8'));
      const policy = proj.settings?.autoExecutionPolicy || proj.autoExecutionPolicy || 'Inherit Global';
      const isEager = policy === 'CASCADE_COMMANDS_AUTO_EXECUTION_EAGER';
      console.log(`- Project "${proj.name || file}": [ ${policy} ] ${isEager ? '🟢' : '⚪'}`);
    } catch (e) {}
  }
}
console.log('');
