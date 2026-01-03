const fs = require('fs');

const NUMBER_OF_USERS = 9000;

function generateRandomString(length, chars) {
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

function generateUsername() {
  const length = Math.floor(Math.random() * 8) + 5; // 5-12 chars
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  return generateRandomString(length, chars);
}

function generatePassword() {
  const lowercase = 'abcdefghijklmnopqrstuvwxyz';
  const uppercase = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const numbers = '0123456789';
  const allChars = lowercase + uppercase + numbers;

  // Ensure at least one of each required type
  let password = '';
  password += lowercase.charAt(Math.floor(Math.random() * lowercase.length));
  password += uppercase.charAt(Math.floor(Math.random() * uppercase.length));
  password += numbers.charAt(Math.floor(Math.random() * numbers.length));

  // Fill remaining length (8-12 total)
  const remainingLength = Math.floor(Math.random() * 5) + 5;
  password += generateRandomString(remainingLength, allChars);

  // Shuffle password
  return password.split('').sort(() => Math.random() - 0.5).join('');
}

function generateUsersCSV(count) {
  const users = new Set();

  while (users.size < count) {
    const username = generateUsername();
    if (!users.has(username)) {
      users.add(username);
    }
  }

  const csvRows = ['userName,password'];
  users.forEach(username => {
    csvRows.push(`${username},${generatePassword()}`);
  });

  fs.writeFileSync('users.csv', csvRows.join('\n'));
  console.log(`✅ Created users.csv with ${count} users`);
}

generateUsersCSV(NUMBER_OF_USERS);