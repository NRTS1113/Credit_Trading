# copy datastore to s3
rclone copy datastore/ wasabi:xtech/credit/datastore -P --progress --stats 5s --checkers 10 --transfers 10

# sync datastore from s3
rclone sync wasabi:xtech/credit/datastore datastore/ -P --progress --stats 5s --checkers 10 --transfers 10
