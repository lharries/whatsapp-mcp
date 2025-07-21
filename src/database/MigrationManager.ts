import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';

export class MigrationManager {
  private db: Database.Database;

  constructor(db: Database.Database) {
    this.db = db;
  }

  async runMigrations(): Promise<void> {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);

    const migrationsDir = path.join(__dirname, '..', '..', 'src', 'database', 'migrations');
    if (!fs.existsSync(migrationsDir)) {
      console.log('No migrations directory found, skipping migrations');
      return;
    }

    const migrationFiles = fs.readdirSync(migrationsDir)
      .filter(file => file.endsWith('.sql'))
      .sort();

    for (const file of migrationFiles) {
      const version = file.replace('.sql', '');
      
      const existing = this.db.prepare(
        'SELECT version FROM schema_migrations WHERE version = ?'
      ).get(version);

      if (!existing) {
        console.log(`Applying migration: ${version}`);
        const migrationSQL = fs.readFileSync(
          path.join(migrationsDir, file), 
          'utf8'
        );
        
        this.db.exec(migrationSQL);
        
        this.db.prepare(
          'INSERT INTO schema_migrations (version) VALUES (?)'
        ).run(version);
        
        console.log(`Migration ${version} applied successfully`);
      }
    }
  }

  rollbackMigration(version: string): void {
    console.log(`Rollback not implemented for version: ${version}`);
  }
}
