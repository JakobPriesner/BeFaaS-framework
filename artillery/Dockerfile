FROM node:20-alpine

RUN npm i -g artillery@latest --allow-root --unsafe-perm=true

WORKDIR /workload

ADD package.json ./
RUN npm install --production

ENV PROCESSOR_DIR /workload

ADD build/index.js ./logger.js
ADD authConfig.js ./authConfig.js

ADD run.sh ./
ADD variables.json ./
ADD workload.yml ./
ADD usernames.csv ./
ADD users.csv ./
ADD users_small.csv ./
ADD image-ambulance.jpg ./
ADD image-noambulance.jpg ./

CMD ["/workload/run.sh"]
