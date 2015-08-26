from app import db
from sqlalchemy.dialects.postgresql import JSONB

from models.github_api import username_and_repo_name_from_github_url
from models.github_api import get_repo_zip_response
from models import github_api
import requests
from util import elapsed
from time import time
import subprocess


class GithubRepo(db.Model):
    login = db.Column(db.Text, primary_key=True)
    repo_name = db.Column(db.Text, primary_key=True)
    language = db.Column(db.Text)
    api_raw = db.Column(JSONB)
    dependency_lines = db.Column(db.Text)
    zip_download_elapsed = db.Column(db.Float)
    zip_download_size = db.Column(db.Integer)
    zip_download_error = db.Column(db.Text)

    def __repr__(self):
        return u'<GithubRepo {language} {login}/{repo_name}>'.format(
            language=self.language, login=self.login, repo_name=self.repo_name)

    def set_github_about(self):
        self.api_raw = github_api.get_repo_data(self.login, self.repo_name)
        return self.api_raw

    def set_github_dependency_lines(self):
        print "getting dependency lines for {}".format(self.full_name)
        r = get_repo_zip_response(self.login, self.repo_name)

        if r.status_code != 200:
            self.zip_download_elapsed = None
            self.zip_download_size = None
            self.zip_download_error = "error {status_code}:{text}".format(
                status_code=r.status_code, text=r.text)
            return None


        start_time = time()
        self.zip_download_elapsed = 0
        self.zip_download_size = 0
        temp_filename = "temp.zip"

        with open(temp_filename, 'wb') as out_file:
            r.raw.decode_content = False

            for chunk in r.iter_content(chunk_size=1024):
                if chunk: # filter out keep-alive new chunks
                    out_file.write(chunk)
                    out_file.flush()
                    self.zip_download_size += 1
                    self.zip_download_elapsed = elapsed(start_time, 4)
                    if self.zip_download_size > 256*1024:
                        print "{}: file too big".format(self.full_name)
                        return None
                    if self.zip_download_elapsed > 60:
                        print "{}: taking too long".format(self.full_name)
                        return None

        print "finished downloading zip for {}".format(self.full_name)

        if self.language == "r":
            query_str = "library|require"
            include_globs = ["*.R", "*.Rnw", "*.Rmd", "*.Rhtml", "*.Rtex", "*.Rst"]
            for glob in include_globs:
                include_globs.append(glob.upper())
                include_globs.append(glob.lower())

            exclude_globs = ["*.foo"]  # hack, because some value is expected

        elif self.language == "python":
            query_str = "import"
            include_globs = ["*.py", "*.ipynb"]
            exclude_globs = ["*/venv/*", "*/virtualenv/*", "*/bin/*", "*/lib/*", "*/library/*"]

        arg_list =['zipgrep', query_str, temp_filename]
        arg_list += include_globs
        arg_list.append("-x")
        arg_list += exclude_globs

        try:
            self.dependency_lines = subprocess.check_output(arg_list)
        except subprocess.CalledProcessError as e:
            print "************************************************************"
            print "zipgrep process died. error: {}".format(e)
            print "************************************************************"
            return None

        print "finished grepping for dependencies for {}".format(self.full_name)

        return self.dependency_lines


    @property
    def full_name(self):
        return self.login + "/" + self.repo_name


# call python main.py add_python_repos_from_google_bucket to run
def add_python_repos_from_google_bucket():

    url = "https://storage.googleapis.com/impactstory/github_python_repo_names.csv"
    add_repos_from_remote_csv(url, "python")


# call python main.py add_r_repos_from_google_bucket to run
def add_r_repos_from_google_bucket():

    url = "https://storage.googleapis.com/impactstory/github_r_repo_names.csv"
    add_repos_from_remote_csv(url, "r")



def add_repos_from_remote_csv(csv_url, language):
    start = time()

    print "going to go get file"
    response = requests.get(csv_url, stream=True)
    index = 0

    for github_url in response.iter_lines(chunk_size=1000):
        login, repo_name = username_and_repo_name_from_github_url(github_url)
        if login and repo_name:
            repo = GithubRepo(
                login=login,
                repo_name=repo_name, 
                language=language
            )
            print repo
            db.session.merge(repo)
            index += 1
            if index % 1000 == 0:
                db.session.commit()
                print "flushing on index {index}, elapsed: {elapsed}".format(
                    index=index, 
                    elapsed=elapsed(start))

    db.session.commit()



"""
add github about api call
"""
def add_github_about(login, repo_name):
    repo = db.session.query(GithubRepo).get((login, repo_name))
    repo.set_github_about()
    db.session.commit()

    print repo

def add_all_github_about():
    q = db.session.query(GithubRepo.login, GithubRepo.repo_name)
    q = q.filter(GithubRepo.api_raw == 'null')
    q = q.order_by(GithubRepo.login)

    for row in q.all():
        #print "setting this row", row
        add_github_about(row[0], row[1])



"""
add github dependency lines
"""
def add_github_dependency_lines(login, repo_name):
    repo = db.session.query(GithubRepo).get((login, repo_name))
    repo.set_github_dependency_lines()
    db.session.commit()

    print "dependency lines found: ", repo.dependency_lines

def add_all_github_dependency_lines():
    q = db.session.query(GithubRepo.login, GithubRepo.repo_name)
    q = q.filter(~GithubRepo.api_raw.has_key('error_code'))
    q = q.order_by(GithubRepo.login)

    for row in q.all():
        #print "setting this row", row
        add_github_dependency_lines(row[0], row[1])






